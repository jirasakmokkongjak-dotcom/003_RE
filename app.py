import os

import pandas as pd
import streamlit as st
from neo4j import GraphDatabase

st.set_page_config(page_title="Neo4j Multi-Strategy Movie Recommender", page_icon="🎬", layout="wide")

# ----------------------------------------------------------------------------
# Sample data (เพิ่มข้อมูล Genres และโครงสร้างความสัมพันธ์)
# ----------------------------------------------------------------------------
USERS = [
    ("U001", "Alex"), ("U002", "Nicha"), ("U003", "Ben"), ("U004", "Waris"),
    ("U005", "Kanya"), ("U006", "Ohm"), ("U007", "Fah"), ("U008", "Tar"),
    ("U009", "Ploy"), ("U010", "Guy"),
]
MOVIES = [
    ("M001", "Iron Man"), ("M002", "The Avengers"), ("M003", "Black Panther"),
    ("M004", "Thor: Ragnarok"), ("M005", "Guardians of the Galaxy"),
    ("M006", "Doctor Strange"), ("M007", "Captain America: Civil War"),
    ("M008", "Spider-Man: Homecoming"), ("M009", "Avengers: Endgame"),
    ("M010", "Ant-Man"),
]
GENRES = [
    ("G01", "Action"), ("G02", "Sci-Fi"), ("G03", "Adventure"), ("G04", "Fantasy")
]
MOVIE_GENRES = [
    ("M001", "G01"), ("M001", "G02"), ("M002", "G01"), ("M002", "G03"),
    ("M003", "G01"), ("M003", "G03"), ("M004", "G01"), ("M004", "G04"),
    ("M005", "G02"), ("M005", "G03"), ("M006", "G04"), ("M007", "G01"),
    ("M007", "G03"), ("M008", "G01"), ("M009", "G01"), ("M009", "G03"),
    ("M010", "G01"), ("M010", "G02"),
]
FRIENDSHIPS = [
    ("U001", "U002"), ("U001", "U003"), ("U001", "U004"),
    ("U002", "U005"), ("U002", "U006"), ("U003", "U007"),
    ("U003", "U008"), ("U004", "U009"), ("U004", "U010"),
    ("U005", "U006"), ("U007", "U008"),
]
WATCHES = [
    ("U001", "M001", "2026-09-01"), ("U001", "M003", "2026-09-02"),
    ("U002", "M002", "2026-09-03"), ("U002", "M001", "2026-09-04"),
    ("U002", "M004", "2026-09-05"), ("U003", "M002", "2026-09-03"),
    ("U003", "M005", "2026-09-06"), ("U003", "M009", "2026-09-07"),
    ("U004", "M002", "2026-09-08"), ("U004", "M006", "2026-09-09"),
    ("U004", "M010", "2026-09-10"), ("U005", "M007", "2026-09-04"),
    ("U006", "M008", "2026-09-05"), ("U007", "M009", "2026-09-06"),
    ("U008", "M004", "2026-09-07"), ("U009", "M003", "2026-09-08"),
    ("U010", "M005", "2026-09-09"),
]

# ----------------------------------------------------------------------------
# Connection
# ----------------------------------------------------------------------------
def default_config() -> dict:
    try:
        s = dict(st.secrets["neo4j"])
    except Exception:
        s = {}
    return {
        "uri": s.get("uri") or os.getenv("NEO4J_URI", ""),
        "user": s.get("user") or os.getenv("NEO4J_USER", "neo4j"),
        "password": s.get("password") or os.getenv("NEO4J_PASSWORD", ""),
    }

@st.cache_resource(show_spinner="กำลังเชื่อมต่อ Neo4j...")
def get_driver(uri: str, user: str, password: str):
    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()
    return driver

def run(query: str, **params) -> pd.DataFrame:
    records, _, _ = st.session_state.driver.execute_query(
        query, parameters_=params, database_=st.session_state.database
    )
    return pd.DataFrame([r.data() for r in records])

def write(query: str, **params) -> None:
    st.session_state.driver.execute_query(
        query, parameters_=params, database_=st.session_state.database
    )

# ----------------------------------------------------------------------------
# Cypher Queries (3 รูปแบบการแนะนำหนัง)
# ----------------------------------------------------------------------------
Q_USERS = "MATCH (u:User) RETURN u.user_id AS id, u.name AS name ORDER BY id"

# 1. แนะนำตามเพื่อนในเครือข่าย (Friend-based)
Q_REC_FRIEND = """
MATCH (me:User {user_id: $user_id})-[:FRIEND_OF]-(friend:User)-[:WATCHED]->(movie:Movie)
WHERE NOT EXISTS { MATCH (me)-[:WATCHED]->(movie) }
RETURN movie.movie_id AS movie_id,
       movie.title AS recommendation,
       count(DISTINCT friend) AS score,
       collect(DISTINCT friend.name) AS details
ORDER BY score DESC, recommendation
"""

# 2. แนะนำตามแนวหนังที่ชอบ (Genre-based)
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

# 3. แนะนำจากผู้ที่มีรสนิยมคล้ายกัน (Collaborative Filtering / Similar Users)
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

Q_WATCHED = """
MATCH (u:User {user_id: $user_id})-[r:WATCHED]->(m:Movie)
RETURN m.movie_id AS movie_id, m.title AS title, toString(r.watch_date) AS watch_date
ORDER BY watch_date
"""

Q_FRIENDS = """
MATCH (:User {user_id: $user_id})-[:FRIEND_OF]-(f:User)
RETURN DISTINCT f.user_id AS friend_id, f.name AS friend ORDER BY friend_id
"""

Q_COUNTS = """
CALL { MATCH (u:User) RETURN count(u) AS users }
CALL { MATCH (m:Movie) RETURN count(m) AS movies }
CALL { MATCH (g:Genre) RETURN count(g) AS genres }
CALL { MATCH ()-[r:FRIEND_OF]->() RETURN count(r) AS friendships }
CALL { MATCH ()-[r:WATCHED]->() RETURN count(r) AS watches }
RETURN users, movies, genres, friendships, watches
"""

def seed_database() -> None:
    write("CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE")
    write("CREATE CONSTRAINT movie_id_unique IF NOT EXISTS FOR (m:Movie) REQUIRE m.movie_id IS UNIQUE")
    write("CREATE CONSTRAINT genre_id_unique IF NOT EXISTS FOR (g:Genre) REQUIRE g.genre_id IS UNIQUE")
    
    write("UNWIND $rows AS row MERGE (u:User {user_id: row.user_id}) SET u.name = row.name", rows=[{"user_id": i, "name": n} for i, n in USERS])
    write("UNWIND $rows AS row MERGE (m:Movie {movie_id: row.movie_id}) SET m.title = row.title", rows=[{"movie_id": i, "title": t} for i, t in MOVIES])
    write("UNWIND $rows AS row MERGE (g:Genre {genre_id: row.genre_id}) SET g.name = row.name", rows=[{"genre_id": i, "name": n} for i, n in GENRES])
    write("UNWIND $rows AS row MATCH (m:Movie {movie_id: row.movie_id}), (g:Genre {genre_id: row.genre_id}) MERGE (m)-[:IN_GENRE]->(g)", rows=[{"movie_id": m, "genre_id": g} for m, g in MOVIE_GENRES])
    write("UNWIND $rows AS row MATCH (a:User {user_id: row.user1}), (b:User {user_id: row.user2}) MERGE (a)-[:FRIEND_OF]->(b)", rows=[{"user1": a, "user2": b} for a, b in FRIENDSHIPS])
    write("UNWIND $rows AS row MATCH (u:User {user_id: row.user_id}), (m:Movie {movie_id: row.movie_id}) MERGE (u)-[r:WATCHED]->(m) SET r.watch_date = date(row.date)", rows=[{"user_id": u, "movie_id": m, "date": d} for u, m, d in WATCHES])

# ----------------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------------
cfg = default_config()
with st.sidebar:
    st.header("🔌 Neo4j Aura")
    uri = st.text_input("URI", cfg["uri"], placeholder="neo4j+s://xxxx.databases.neo4j.io")
    user = st.text_input("Username", cfg["user"])
    password = st.text_input("Password", cfg["password"], type="password")
    connect = st.button("Connect", type="primary", use_container_width=True)

if connect or (cfg["uri"] and cfg["password"] and "driver" not in st.session_state):
    try:
        driver = get_driver(uri or cfg["uri"], user or cfg["user"], password or cfg["password"])
        records, _, _ = driver.execute_query("SHOW HOME DATABASE")
        st.session_state.driver = driver
        st.session_state.database = records[0]["name"]
    except Exception as e:
        st.sidebar.error(f"เชื่อมต่อไม่สำเร็จ: {e}")

st.title("🎬 Neo4j Multi-Strategy Movie Recommender")
st.caption("ระบบแนะนำหนังหลายรูปแบบด้วย Graph Traversal บน Neo4j")

if "driver" not in st.session_state:
    st.info("กรอกข้อมูลเชื่อมต่อที่แถบด้านซ้าย แล้วกด **Connect**")
    st.stop()

st.sidebar.success(f"Connected · database: `{st.session_state.database}`")

tab_rec, tab_user, tab_stats, tab_setup = st.tabs(
    ["🎯 ระบบแนะนำหนัง", "👤 ข้อมูลผู้ใช้", "📊 สถิติภาพรวม", "⚙️ ตั้งค่าฐานข้อมูล"]
)

users_df = run(Q_USERS)

# ----------------------------------------------------------------------------
# Setup Tab
# ----------------------------------------------------------------------------
with tab_setup:
    st.subheader("จัดการข้อมูลตัวอย่างในฐานข้อมูล")
    if st.button("Seed sample data"):
        with st.spinner("กำลังสร้างข้อมูล..."):
            seed_database()
        st.success("สร้างข้อมูลสำเร็จ!")
        st.rerun()
    counts = run(Q_COUNTS)
    if not counts.empty:
        c = counts.iloc[0]
        cols = st.columns(5)
        cols[0].metric("Users", int(c["users"]))
        cols[1].metric("Movies", int(c["movies"]))
        cols[2].metric("Genres", int(c["genres"]))
        cols[3].metric("Friendships", int(c["friendships"]))
        cols[4].metric("Watches", int(c["watches"]))

if users_df.empty:
    for t in (tab_rec, tab_user, tab_stats):
        with t:
            st.warning("ยังไม่มีข้อมูล — ไปที่แท็บ **⚙️ ตั้งค่าฐานข้อมูล** แล้วกดปุ่ม Seed sample data ก่อน")
    st.stop()

# User Picker ใน Sidebar
labels = {r.id: f"{r.id} · {r['name']}" for _, r in users_df.iterrows()}
with st.sidebar:
    st.divider()
    user_id = st.selectbox("เลือกผู้ใช้งาน", list(labels), format_func=labels.get)
user_name = users_df.set_index("id").loc[user_id, "name"]

# ----------------------------------------------------------------------------
# Recommend Tab (รวมระบบแนะนำหนังหลายรูปแบบ)
# ----------------------------------------------------------------------------
with tab_rec:
    st.subheader(f"🎯 ระบบแนะนำหนังสำหรับ: {user_name}")
    
    # เลือกกลยุทธ์การแนะนำหนัง
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
    
    # ดึงข้อมูลตามกลยุทธ์ที่เลือก
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
        st.info("ไม่มีหนังแนะนำสำหรับเงื่อนไขนี้ (ผู้ใช้อาจดูหนังครบหมดแล้ว หรือไม่มีความเชื่อมโยงในเงื่อนไขดังกล่าว)")
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