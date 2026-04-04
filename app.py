import os
from flask import Flask, flash, redirect, render_template, request, session, abort, url_for, jsonify
from flask_session import Session
from flask_compress import Compress
from supabase import create_client, Client
from dotenv import load_dotenv
import math
import time
from google import genai
from google.genai import types

load_dotenv()

supabase: Client = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_PUBLISHABLE_KEY")
)

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

app = Flask(__name__)
Compress(app)

# ── Cache ────────────────────────────────────────────────

_cache = {}

def cached_query(key, query_fn, ttl=3600):
    """Cache a Supabase query result in memory for `ttl` seconds (default 1 hour)."""
    now = time.time()
    if key in _cache and now - _cache[key]["time"] < ttl:
        return _cache[key]["data"]
    data = query_fn()
    _cache[key] = {"data": data, "time": now}
    return data

# ── Helpers ──────────────────────────────────────────────

def paginate(query, page, per_page=20):
    """Run a Supabase query with pagination. Returns (data, total_pages)."""
    start = (page - 1) * per_page
    end = start + per_page - 1
    response = query.range(start, end).execute()
    total = response.count if hasattr(response, 'count') and response.count is not None else 0
    total_pages = max(1, math.ceil(total / per_page))
    return response.data, total_pages


def get_counts():
    """Return total poems, poets, meters, themes counts for homepage stats."""
    poems_count = supabase.table("poems").select("id", count="exact").limit(1).execute()
    poets_count = supabase.table("poets").select("id", count="exact").limit(1).execute()
    meters_count = supabase.table("meters").select("id", count="exact").limit(1).execute()
    themes_count = supabase.table("themes").select("id", count="exact").limit(1).execute()
    return {
        "poems": poems_count.count if poems_count.count else 0,
        "poets": poets_count.count if poets_count.count else 0,
        "meters": meters_count.count if meters_count.count else 0,
        "themes": themes_count.count if themes_count.count else 0,
    }


# ── HTTP Cache Headers ───────────────────────────────────

@app.after_request
def add_cache_headers(response):
    if request.path.startswith('/static/'):
        response.cache_control.max_age = 31536000
        response.cache_control.public = True
    return response


# ── Routes ───────────────────────────────────────────────

@app.route("/")
def index():
    response = supabase.table("poets").select("id, name, slug").limit(6).execute()
    poets = response.data
    stats = cached_query("homepage_stats", get_counts, ttl=3600)
    return render_template("index.html", poets=poets, stats=stats)


@app.route("/poems")
def poems():
    page = request.args.get("page", 1, type=int)
    per_page = 20

    # Build the query
    query = supabase.table("poems").select(
        "id, title, slug, poets(name), meters(name), themes(name)",
        count="exact"
    ).order("id")

    # Apply filters if present
    meter_filter = request.args.get("meter")
    rhyme_filter = request.args.get("rhyme")
    theme_filter = request.args.get("theme")

    if meter_filter:
        query = query.eq("meter_id", meter_filter)
    if theme_filter:
        query = query.eq("theme_id", theme_filter)
    if rhyme_filter:
        query = query.eq("rhyme_id", rhyme_filter)

    poems_data, total_pages = paginate(query, page, per_page)

    # Fetch filter options (cached — these rarely change)
    meters_list = cached_query("filter_meters", lambda: supabase.table("meters").select("id, name").execute().data)
    themes_list = cached_query("filter_themes", lambda: supabase.table("themes").select("id, name").execute().data)
    rhymes_list = cached_query("filter_rhymes", lambda: supabase.table("rhymes").select("id, pattern").execute().data)

    return render_template(
        "poems.html",
        poems=poems_data,
        page=page,
        total_pages=total_pages,
        meters=meters_list,
        themes=themes_list,
        rhymes=rhymes_list,
        current_meter=meter_filter,
        current_theme=theme_filter,
        current_rhyme=rhyme_filter,
    )


@app.route("/poets")
def poets():
    page = request.args.get("page", 1, type=int)
    per_page = 20
    query = supabase.table("poets").select("id, name, slug, poem_count", count="exact")
    poets_data, total_pages = paginate(query, page, per_page)
    return render_template("poets.html", poets=poets_data, page=page, total_pages=total_pages)


@app.route("/poem/<slug>")
def poem(slug):
    response = supabase.table("poems").select(
        "content, title, slug, meters(name), rhymes(pattern), poets(name, slug, eras(name))"
    ).eq("slug", slug).execute()

    if not response.data:
        abort(404)

    poem = response.data[0]
    verses = poem["content"].split("*")
    return render_template("poem.html", verses=verses, poem=poem)


@app.route("/poet/<slug>")
def poet(slug):
    page = request.args.get("page", 1, type=int)
    per_page = 20

    poet_res = supabase.table("poets").select("id, name, slug, eras(name)").eq("slug", slug).execute()
    if not poet_res.data:
        abort(404)
    poet = poet_res.data[0]

    query = supabase.table("poems").select(
        "slug, title, id, meters(name), themes(name)", count="exact"
    ).eq("poet_id", poet["id"]).order("id")

    poems_data, total_pages = paginate(query, page, per_page)
    return render_template("poet.html", poems=poems_data, poet=poet, page=page, total_pages=total_pages)


@app.route("/meter/<slug>")
def meter(slug):
    page = request.args.get("page", 1, type=int)
    per_page = 20

    meter_res = supabase.table("meters").select("id, name, slug").eq("slug", slug).execute()
    if not meter_res.data:
        abort(404)
    meter = meter_res.data[0]

    query = supabase.table("poems").select(
        "slug, title, id, meters(name), themes(name), poets(name)", count="exact"
    ).eq("meter_id", meter["id"]).order("id")

    poems_data, total_pages = paginate(query, page, per_page)
    return render_template("meter.html", poems=poems_data, meter=meter, page=page, total_pages=total_pages)


@app.route("/meters")
def meters():
    meters = cached_query("meters", lambda: supabase.table("meters").select("id, name, slug, poem_count").execute().data)
    return render_template("meters.html", meters=meters)


@app.route("/rhyme/<slug>")
def rhyme(slug):
    page = request.args.get("page", 1, type=int)
    per_page = 20

    rhyme_res = supabase.table("rhymes").select("id, pattern, slug").eq("slug", slug).execute()
    if not rhyme_res.data:
        abort(404)
    rhyme = rhyme_res.data[0]

    query = supabase.table("poems").select(
        "slug, title, id, meters(name), themes(name), poets(name)", count="exact"
    ).eq("rhyme_id", rhyme["id"]).order("id")

    poems_data, total_pages = paginate(query, page, per_page)
    return render_template("rhyme.html", poems=poems_data, rhyme=rhyme, page=page, total_pages=total_pages)


@app.route("/rhymes")
def rhymes():
    rhymes = cached_query("rhymes", lambda: supabase.table("rhymes").select("id, pattern, slug, poem_count").execute().data)
    return render_template("rhymes.html", rhymes=rhymes)


@app.route("/theme/<slug>")
def theme(slug):
    page = request.args.get("page", 1, type=int)
    per_page = 20

    theme_res = supabase.table("themes").select("id, name, slug").eq("slug", slug).execute()
    if not theme_res.data:
        abort(404)
    theme = theme_res.data[0]

    query = supabase.table("poems").select(
        "slug, title, id, meters(name), themes(name), poets(name)", count="exact"
    ).eq("theme_id", theme["id"]).order("id")

    poems_data, total_pages = paginate(query, page, per_page)
    return render_template("theme.html", poems=poems_data, theme=theme, page=page, total_pages=total_pages)


@app.route("/themes")
def themes():
    themes = cached_query("themes", lambda: supabase.table("themes").select("id, name, slug, poem_count").execute().data)
    return render_template("themes.html", themes=themes)


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return render_template("search.html", q="", poems=[], poets=[], content_matches=[])

    # Search poems by title (fast — title is a short column)
    try:
        poems_res = supabase.table("poems").select(
            "id, title, slug, poets(name), meters(name)"
        ).ilike("title", f"%{q}%").limit(20).execute()
        poems_data = poems_res.data
    except Exception:
        poems_data = []

    # Search poets by name (fast — name is a short column)
    try:
        poets_res = supabase.table("poets").select(
            "id, name, slug"
        ).ilike("name", f"%{q}%").limit(20).execute()
        poets_data = poets_res.data
    except Exception:
        poets_data = []

    # Search inside poem content (may timeout on large datasets — that's OK)
    content_matches = []
    try:
        content_res = supabase.table("poems").select(
            "id, title, slug, poets(name)"
        ).ilike("content", f"%{q}%").limit(10).execute()
        title_ids = {p["id"] for p in poems_data}
        content_matches = [p for p in content_res.data if p["id"] not in title_ids]
    except Exception:
        pass

    return render_template(
        "search.html",
        q=q,
        poems=poems_data,
        poets=poets_data,
        content_matches=content_matches,
    )


# ── Gemini AI Explanation ────────────────────────────────

@app.route("/api/explain/<slug>", methods=["POST"])
def explain_poem(slug):
    # Fetch the poem
    poem_res = supabase.table("poems").select(
        "title, content, poets(name)"
    ).eq("slug", slug).execute()

    if not poem_res.data:
        return jsonify({"error": "القصيدة غير موجودة"}), 404

    poem = poem_res.data[0]
    verses_text = poem["content"].replace("*", "\n")

    system_instruction = "أنت خبير في الأدب العربي والشعر. مهمتك هي شرح القصائد العربية بأسلوب أدبي رفيع ومبسط في آن واحد. لا تستخدم رموزاً غريبة مثل (££) في مخرجاتك. تأكد من أن يكون الشرح منظماً وواضحاً."

    # Call Gemini
    try:
        prompt = f"""اشرح هذه القصيدة العربية شرحاً أدبياً وافياً:

العنوان: {poem['title']}
الشاعر: {poem['poets']['name'] if poem['poets'] else 'غير معروف'}

الأبيات:
{verses_text}

المطلوب:
١. المعنى الإجمالي: شرح الفكرة العامة للقصيدة.
٢. تحليل الأبيات: شرح المعاني اللغوية والسياقية لكل بيت بشكل مبسط.
٣. الجماليات: ذكر أهم التشبيهات والمحسنات البديعية.
٤. العاطفة: تحليل الحالة النفسية للشاعر وتأثيرها على النص."""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7
            )
        )
        
        explanation = response.text
        # Clean up unwanted characters if any
        explanation = explanation.replace("££", "").strip()
        
        return jsonify({"explanation": explanation})

    except Exception as e:
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500


# ── Error handlers ───────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404