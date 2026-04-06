import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

supabase = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_PUBLISHABLE_KEY")
)

try:
    poems_res = supabase.table("poems").select(
        "id, title"
    ).textSearch("search_vector", "الحب", type="websearch", config="simple").limit(5).execute()
    print("SUCCESS POEMS:", poems_res.data)
except Exception as e:
    import traceback
    traceback.print_exc()
