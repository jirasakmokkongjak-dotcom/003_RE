import os

import pandas as pd
import streamlit as st
from neo4j import GraphDatabase

st.set_page_config(page_title="Neo4j Movie Recommender", page_icon="🎬", layout="wide")

# ----------------------------------------------------------------------------
# Sample data: เพิ่ม Genres และความสัมพันธ์ของหนังกับ Genre
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
# กำหนดว่าหนังเรื่องไหนอยู่แนวไหนบ้าง
MOVIE_GENRES = [
    ("M001", "G01"), ("M001", "G02"),
    ("M002", "G01"), ("M002", "G03"), ("M003", "G01"), ("M003", "G03"),
    ("M004", "G01"), ("M004", "G04"), ("M005", "G02"), ("M005", "G03"),
    ("M006", "G04"), ("M007", "G01"), ("M007", "G03"), ("M008", "G01"),
    ("M009", "G01"), ("M009", "G03"), ("M010", "G01"), ("M010", "G02"),
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
# Cypher (ปรับเปลี่ยนระบบแนะนำเป็น Genre-based)
# ----------------------------------------------------------------------------
Q_USERS = "MATCH (u:User) RETURN u.user_id AS id, u.name AS name ORDER BY id"

# แนะนำหนังตามแนว (Genre) ที่ผู้ใช้เคยดูบ่อย แต่ยังไม่เคยรับชมเรื่องนั้นๆ
Q_RECOMMEND = """
MATCH (me:User {user_id: $user_id})-[:WATCHED]->(:Movie)-[:IN_GENRE]->(g:Genre)
<-[:IN_GENRE]-(rec:Movie)
WHERE NOT EXISTS { MATCH (me)-[:WATCHED]->(rec) }
RETURN rec.movie_id AS movie_id,
       rec.title AS recommendation,
       count(DISTINCT g) AS genre_score,
       collect(DISTINCT g.name) AS shared_genres
ORDER BY genre_score DESC, recommendation
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

Q_MOVIES_PER_USER = """
MATCH (u:User)-[:WATCHED]->(m:Movie)
RETURN u.name AS user, count(m) AS total_movies ORDER BY total_movies DESC, user
"""

Q_WATCH_COUNT = """
MATCH (:User)-[:WATCHED]->(m:Movie)
RETURN m.title AS movie, count(*) AS watch_count ORDER BY watch_count DESC, movie
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
    
    write(
        "UNWIND $rows AS row MERGE (u:User {user_id: row.user_id}) SET u.name = row.name",
        rows=[{"user_id": i, "name": n} for i, n in USERS],
    )
    write(
        "UNWIND $rows AS row MERGE (m:Movie {movie_id: row.movie_id}) SET m.title = row.title",
        rows=[{"movie_id": i, "title": t} for i, t in MOVIES],
    )
    write(
        "UNWIND $rows AS row MERGE (g:Genre {genre_id: row.genre_id}) SET g.name = row.name",
        rows=[{"genre_id": i, "name": n} for i, n in GENRES],
    )
    write(
        """UNWIND $rows AS row
           MATCH (m:Movie {movie_id: row.movie_id}), (g:Genre {genre_id: row.genre_id})
           MERGE (m)-[:IN_GENRE]->(g)""",
        rows=[{"movie_id": m, "genre_id": g} for m, g in MOVIE_GENRES],
    )
    write(
        """UNWIND $rows AS row
           MATCH (a:User {user_id: row.user1}), (b:User {user_id: row.user2})
           MERGE (a)-[:FRIEND_OF]->(b)""",
        rows=[{"user1": a, "user2": b} for a, b in FRIENDSHIPS],
    )
    write(
        """UNWIND $rows AS row
           MATCH (u:User {user_id: row.user_id}), (m:Movie {movie_id: row.movie_id})
           MERGE (u)-[r:WATCHED]->(m)
           SET r.watch_date = date(row.date)""",
        rows=[{"user_id": u, "movie_id": m, "date": d} for u, m, d in WATCHES],
    )

# ----------------------------------------------------------------------------
# Sidebar: connect
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

st.title("🎬 Neo4j Genre-based Movie Recommendation")
st.caption("แนะนำหนังตามแนวภาพยนตร์ (Genre) ที่ผู้ใช้ชื่นชอบ ด้วย Graph Traversal บน Neo4j")

if "driver" not in st.session_state:
    st.info("กรอกข้อมูลเชื่อมต่อที่แถบด้านซ้าย แล้วกด **Connect**")
    st.stop()

st.sidebar.success(f"Connected · database: `{st.session_state.database}`")

tab_rec, tab_user, tab_stats, tab_graph, tab_setup = st.tabs(
    ["🎯 Recommend", "👤 User", "📊 Analytics", "🕸️ Graph", "⚙️ Setup"]
)

users_df = run(Q_USERS)

# ----------------------------------------------------------------------------
# Setup
# ----------------------------------------------------------------------------
with tab_setup:
    st.subheader("สร้างข้อมูลตัวอย่าง (รวม Genres)")
    st.write("สร้าง Constraint, User, Movie, Genre, ความสัมพันธ์ IN_GENRE, FRIEND_OF และ WATCHED")
    if st.button("Seed sample data"):
        with st.spinner("กำลังสร้างข้อมูล..."):
            seed_database()
        st.success("เสร็จแล้ว")
        st.rerun()
    counts = run(Q_COUNTS)
    if not counts.empty:
        c = counts.iloc[0]
        cols = st.columns(5)
        cols[0].metric("Users", int(c["users"]))
        cols[1].metric("Movies", int(c["movies"]))
        cols[2].metric("Genres", int(c["genres"]))
        cols[3].metric("FRIEND_OF", int(c["friendships"]))
        cols[4].metric("WATCHED", int(c["watches"]))

if users_df.empty:
    for t in (tab_rec, tab_user, tab_stats, tab_graph):
        with t:
            st.warning("ยังไม่มีข้อมูล — ไปที่แท็บ **Setup** แล้วกด Seed sample data")
    st.stop()

# user picker shared across tabs
labels = {r.id: f"{r.id} · {r['name']}" for _, r in users_df.iterrows()}
with st.sidebar:
    st.divider()
    user_id = st.selectbox("เลือกผู้ใช้", list(labels), format_func=labels.get)
user_name = users_df.set_index("id").loc[user_id, "name"]

# ----------------------------------------------------------------------------
# Recommend (Genre-based)
# ----------------------------------------------------------------------------
with tab_rec:
    st.subheader(f"หนังที่แนะนำให้ {user_name} (อ้างอิงจากแนวหนังที่ชอบ)")
    rec = run(Q_RECOMMEND, user_id=user_id)
    if rec.empty:
        st.info("ไม่มีหนังแนะนำ — ผู้ใช้อาจดูหนังครบทุกเรื่องแล้ว หรือยังไม่ได้ดูหนังเลย")
    else:
        left, right = st.columns([3, 2])
        with left:
            st.dataframe(
                rec.assign(shared_genres=rec["shared_genres"].map(", ".join)),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "movie_id": "Movie ID",
                    "recommendation": "หนัง",
                    "genre_score": st.column_config.ProgressColumn(
                        "genre_score", min_value=0, max_value=int(rec["genre_score"].max()), format="%d"
                    ),
                    "shared_genres": "แนวหนังที่ตรงกัน",
                },
            )
        with right:
            st.bar_chart(rec.set_index("recommendation")["genre_score"])
    with st.expander("Cypher ที่ใช้"):
        st.code(Q_RECOMMEND, language="cypher")
    st.caption("genre_score = จำนวนแนวหนัง (Genres) ที่ซ้อนทับกับประวัติการดูของผู้ใช้")

# ----------------------------------------------------------------------------
# User
# ----------------------------------------------------------------------------
with tab_user:
    st.subheader(f"ข้อมูลของ {user_name}")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**หนังที่เคยดู**")
        st.dataframe(run(Q_WATCHED, user_id=user_id), hide_index=True, use_container_width=True)
    with c2:
        st.markdown("**เพื่อน**")
        st.dataframe(run(Q_FRIENDS, user_id=user_id), hide_index=True, use_container_width=True)

# ----------------------------------------------------------------------------
# Analytics
# ----------------------------------------------------------------------------
with tab_stats:
    a, b = st.columns(2)
    with a:
        st.markdown("**จำนวนหนังที่ผู้ใช้แต่ละคนดู**")
        df = run(Q_MOVIES_PER_USER)
        if not df.empty:
            st.bar_chart(df.set_index("user")["total_movies"])
    with b:
        st.markdown("**หนังที่มีคนดูมากที่สุด**")
        df = run(Q_WATCH_COUNT)
        if not df.empty:
            st.bar_chart(df.set_index("movie")["watch_count"])

# ----------------------------------------------------------------------------
# Graph
# ----------------------------------------------------------------------------
def esc(s: str) -> str:
    return str(s).replace('"', '\\"')

with tab_graph:
    st.subheader(f"Ego graph ของ {user_name} (User -> Movie -> Genre)")
    mine = run(Q_WATCHED, user_id=user_id)
    rec_df = run(Q_RECOMMEND, user_id=user_id)
    rec_titles = set(rec_df.get("recommendation", []))
    mine_titles = set(mine.get("title", []))

    # ดึงข้อมูล Genre ของหนังที่ผู้ใช้ดู
    Q_USER_GENRES = """
    MATCH (u:User {user_id: $user_id})-[:WATCHED]->(m:Movie)-[:IN_GENRE]->(g:Genre)
    RETURN DISTINCT m.title AS movie, g.name AS genre
    """
    ug_df = run(Q_USER_GENRES, user_id=user_id)

    dot = ["digraph G { rankdir=LR; node [style=filled, fontname=Helvetica];"]
    dot.append(f'"me" [label="{esc(user_name)}", shape=circle, fillcolor="#4F8BF9", fontcolor=white];')
    
    for m in mine_titles:
        dot.append(f'"m_{esc(m)}" [label="{esc(m)}", shape=box, fillcolor="#B7E4C7"];')
        dot.append(f'"me" -> "m_{esc(m)}" [label="WATCHED", fontsize=9, color="#2D6A4F"];')

    for _, row in ug_df.iterrows():
        dot.append(f'"g_{esc(row.genre)}" [label="{esc(row.genre)}", shape=ellipse, fillcolor="#FFD166"];')
        dot.append(f'"m_{esc(row.movie)}" -> "g_{esc(row.genre)}" [label="IN_GENRE", fontsize=9];')

    dot.append("}")
    st.graphviz_chart("\n".join(dot), use_container_width=True)
    st.caption("🟩 หนังที่เคยดู · 🟨 แนวหนัง (Genre)")