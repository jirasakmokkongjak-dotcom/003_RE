import os
import pandas as pd
import streamlit as st
from neo4j import GraphDatabase

st.set_page_config(page_title="Neo4j Multi-Strategy Movie Recommender", page_icon="🎬", layout="wide")

# ----------------------------------------------------------------------------
# Connection
# ----------------------------------------------------------------------------
def get_config() -> dict:
    try:
        s = dict(st.secrets["neo4j"])
    except Exception:
        s = {}
    return {
        "uri": s.get("uri") or os.getenv("NEO4J_URI", ""),
        "user": s.get("username") or s.get("user") or os.getenv("NEO4J_USER", "neo4j"),
        "password": s.get("password") or os.getenv("NEO4J_PASSWORD", ""),
        "database": s.get("database", "neo4j"),
    }

@st.cache_resource(show_spinner="กำลังเชื่อมต่อฐานข้อมูล Neo4j...")
def init_driver(uri: str, user: str, password: str):
    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()
    return driver

# ดำเนินการเชื่อมต่ออัตโนมัติ
cfg = get_config()
try:
    driver = init_driver(cfg["uri"], cfg["user"], cfg["password"])
    st.session_state.driver = driver
    st.session_state.database = cfg["database"]
except Exception as e:
    st.error(f"❌ ไม่สามารถเชื่อมต่อ Neo4j ได้ กรุณาเช็คการตั้งค่า Secrets: {e}")
    st.stop()

def run(query: str, **params) -> pd.DataFrame:
    records, _, _ = st.session_state.driver.execute_query(
        query, parameters_=params, database_=st.session_state.database
    )
    return pd.DataFrame([r.data() for r in records])

# ----------------------------------------------------------------------------
# Cypher Queries
# ----------------------------------------------------------------------------
Q_USERS = "MATCH (u:User) RETURN u.user_id AS id, u.name AS name ORDER BY id"

# 1. แนะนำตามเพื่อนในเครือข่าย (Friend-based Movie Rec)
Q_REC_FRIEND = """
MATCH (me:User {user_id: $user_id})-[:FRIEND_OF]-(friend:User)-[:WATCHED]->(movie:Movie)
WHERE NOT EXISTS { MATCH (me)-[:WATCHED]->(movie) }
RETURN movie.movie_id AS movie_id,
       movie.title AS recommendation,
       count(DISTINCT friend) AS score,
       collect(DISTINCT friend.name) AS details
ORDER BY score DESC, recommendation
"""

# 2. แนะนำตามแนวหนังที่ชอบ (Genre-based Movie Rec)
Q_REC_GENRE = """
MATCH (me:User {user_id: $user_id})-[:WATCHED]->(:Movie)-[:IN_GENRE]->(g:Genre)
<-[:IN_GENRE]-(rec:Movie)
WHERE NOT EXISTS { MATCH (me)-[:WATCHED]->(rec) }
RETURN rec.movie_id AS movie_id,
       rec.title AS recommendation,
       count(DISTINCT g) AS score,
       collect(DISTINCT g.name) AS details
ORDER BY score DESC, recommendation
"""

# 3. แนะนำจากผู้ที่มีรสนิยมคล้ายกัน (Collaborative Filtering Movie Rec)
Q_REC_SIMILAR_USERS = """
MATCH (me:User {user_id: $user_id})-[:WATCHED]->(m:Movie)<-[:WATCHED]-(other:User)
WHERE other <> me
MATCH (other)-[:WATCHED]->(rec:Movie)
WHERE NOT EXISTS { MATCH (me)-[:WATCHED]->(rec) }
RETURN rec.movie_id AS movie_id,
       rec.title AS recommendation,
       count(DISTINCT other) AS score,
       collect(DISTINCT other.name) AS details
ORDER BY score DESC, recommendation
"""

# 4. แนะนำเพื่อน (Friend Recommendation: Mutual Friends / Friends of Friends)
Q_REC_FRIEND_SUGGESTION = """
MATCH (me:User {user_id: $user_id})-[:FRIEND_OF]-(mutual:User)-[:FRIEND_OF]-(suggested:User)
WHERE me <> suggested
  AND NOT (me)-[:FRIEND_OF]-(suggested)
RETURN suggested.user_id AS user_id,
       suggested.name AS friend_name,
       count(DISTINCT mutual) AS mutual_count,
       collect(DISTINCT mutual.name) AS mutual_friends
ORDER BY mutual_count DESC, friend_name
"""

Q_WATCHED = """
MATCH (u:User {user_id: $user_id})-[r:WATCHED]->(m:Movie)
RETURN m.movie_id AS movie_id, m.title AS title, toString(r.watch_date) AS watch_date
ORDER BY watch_date
"""

Q_FRIENDS = """
MATCH (:User {user_id: $user_id})-[:FRIEND_OF]-(f:User)
RETURN DISTINCT f.user_id AS friend_id, f.name AS friend ORDER BY friend_id
"""

# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------
st.title("🎬 Neo4j Multi-Strategy Movie Recommender")
st.caption("ระบบแนะนำหนังและเพื่อนด้วย Graph Traversal บน Neo4j")

users_df = run(Q_USERS)

if users_df.empty:
    st.warning("ไม่พบข้อมูลผู้ใช้งาน (User) ในฐานข้อมูล")
    st.stop()

# Sidebar ตัวเลือก User
labels = {r.id: f"{r.id} · {r['name']}" for _, r in users_df.iterrows()}
with st.sidebar:
    st.header("👤 ตัวเลือก")
    user_id = st.selectbox("เลือกผู้ใช้งาน", list(labels), format_func=labels.get)

user_name = users_df.set_index("id").loc[user_id, "name"]

tab_rec, tab_friend_rec, tab_user, tab_stats = st.tabs(
    ["🎯 ระบบแนะนำหนัง", "👥 แนะนำเพื่อน", "👤 ข้อมูลผู้ใช้", "📊 สถิติภาพรวม"]
)

# ----------------------------------------------------------------------------
# Recommend Tab (ระบบแนะนำหนัง)
# ----------------------------------------------------------------------------
with tab_rec:
    st.subheader(f"🎯 ระบบแนะนำหนังสำหรับ: {user_name}")
    
    strategy = st.radio(
        "เลือกอัลกอริทึมการแนะนำหนัง:",
        [
            "1. แนะนำจากเพื่อนในกลุ่ม (Friend-based)",
            "2. แนะนำจากแนวหนังที่ชื่นชอบ (Genre-based)",
            "3. แนะนำจากผู้ที่มีรสนิยมคล้ายกัน (Collaborative Filtering)"
        ],
        horizontal=True
    )
    
    st.divider()
    
    if "1." in strategy:
        rec = run(Q_REC_FRIEND, user_id=user_id)
        score_label = "จำนวนเพื่อนที่ดู"
        details_label = "เพื่อนที่เคยดู"
        cypher_used = Q_REC_FRIEND
    elif "2." in strategy:
        rec = run(Q_REC_GENRE, user_id=user_id)
        score_label = "ความสอดคล้องของแนวหนัง"
        details_label = "แนวหนังที่ตรงกัน"
        cypher_used = Q_REC_GENRE
    else:
        rec = run(Q_REC_SIMILAR_USERS, user_id=user_id)
        score_label = "จำนวนผู้ใช้ที่ดูเหมือนกัน"
        details_label = "ผู้ใช้ที่มีรสนิยมคล้ายกัน"
        cypher_used = Q_REC_SIMILAR_USERS

    if rec.empty:
        st.info("ไม่มีหนังแนะนำสำหรับเงื่อนไขนี้")
    else:
        left, right = st.columns([3, 2])
        with left:
            st.dataframe(
                rec.assign(details=rec["details"].map(", ".join)),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "movie_id": "Movie ID",
                    "recommendation": "ชื่อภาพยนตร์",
                    "score": st.column_config.ProgressColumn(
                        score_label, min_value=0, max_value=int(rec["score"].max()), format="%d"
                    ),
                    "details": details_label,
                },
            )
        with right:
            st.bar_chart(rec.set_index("recommendation")["score"])
            
    with st.expander("ดูชุดคำสั่ง Cypher Query ที่ใช้ประมวลผล"):
        st.code(cypher_used, language="cypher")

# ----------------------------------------------------------------------------
# Friend Recommendation Tab (แท็บแนะนำเพื่อน)
# ----------------------------------------------------------------------------
with tab_friend_rec:
    st.subheader(f"👥 ระบบแนะนำเพื่อนสำหรับ: {user_name}")
    st.caption("คำนวณจากคนที่มีเพื่อนร่วมกัน (Mutual Friends / Friends of Friends)")
    
    rec_friends = run(Q_REC_FRIEND_SUGGESTION, user_id=user_id)
    
    if rec_friends.empty:
        st.info("ไม่พบคำแนะนำเพื่อนสำหรับผู้ใช้นี้ (อาจจะเป็นเพื่อนกับทุกคนในระบบแล้ว หรือไม่มีเพื่อนร่วมกัน)")
    else:
        f_left, f_right = st.columns([3, 2])
        with f_left:
            st.dataframe(
                rec_friends.assign(mutual_friends=rec_friends["mutual_friends"].map(", ".join)),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "user_id": "User ID",
                    "friend_name": "ชื่อผู้ใช้ที่แนะนำ",
                    "mutual_count": st.column_config.ProgressColumn(
                        "จำนวนเพื่อนร่วมกัน", min_value=0, max_value=int(rec_friends["mutual_count"].max()), format="%d"
                    ),
                    "mutual_friends": "เพื่อนร่วมกัน",
                },
            )
        with f_right:
            st.bar_chart(rec_friends.set_index("friend_name")["mutual_count"])

    with st.expander("ดูชุดคำสั่ง Cypher Query ที่ใช้ประมวลผล"):
        st.code(Q_REC_FRIEND_SUGGESTION, language="cypher")

# ----------------------------------------------------------------------------
# User Tab
# ----------------------------------------------------------------------------
with tab_user:
    st.subheader(f"👤 ข้อมูลส่วนตัวของ {user_name}")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🎬 หนังที่เคยรับชม**")
        st.dataframe(run(Q_WATCHED, user_id=user_id), hide_index=True, use_container_width=True)
    with c2:
        st.markdown("**🤝 เพื่อนในเครือข่าย**")
        st.dataframe(run(Q_FRIENDS, user_id=user_id), hide_index=True, use_container_width=True)

# ----------------------------------------------------------------------------
# Stats Tab
# ----------------------------------------------------------------------------
with tab_stats:
    st.subheader("📊 สถิติภาพรวมระบบ")
    a, b = st.columns(2)
    with a:
        st.markdown("**จำนวนหนังที่ผู้ใช้แต่ละคนดู**")
        df_u = run("MATCH (u:User)-[:WATCHED]->(m:Movie) RETURN u.name AS user, count(m) AS total_movies ORDER BY total_movies DESC")
        if not df_u.empty:
            st.bar_chart(df_u.set_index("user")["total_movies"])
    with b:
        st.markdown("**ภาพยนตร์ที่มีผู้ชมมากที่สุด**")
        df_m = run("MATCH (:User)-[:WATCHED]->(m:Movie) RETURN m.title AS movie, count(*) AS watch_count ORDER BY watch_count DESC")
        if not df_m.empty:
            st.bar_chart(df_m.set_index("movie")["watch_count"])