"""Neo4j Movie Recommendation System — Streamlit UI

Run:  streamlit run app.py
"""
import os

import pandas as pd
import streamlit as st
from neo4j import GraphDatabase

st.set_page_config(page_title="Neo4j Movie Recommender", page_icon="🎬", layout="wide")

# ----------------------------------------------------------------------------
# Sample data (ตรงกับ README: 10 users, 10 movies) — แก้ไขได้ตามใน notebook
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
    """อ่านค่าจาก .streamlit/secrets.toml ก่อน แล้วค่อย environment variables"""
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
    """รัน Cypher แบบ parameterized แล้วคืนเป็น DataFrame (เหมือนใน notebook)"""
    records, _, _ = st.session_state.driver.execute_query(
        query, parameters_=params, database_=st.session_state.database
    )
    return pd.DataFrame([r.data() for r in records])


def write(query: str, **params) -> None:
    st.session_state.driver.execute_query(
        query, parameters_=params, database_=st.session_state.database
    )


# ----------------------------------------------------------------------------
# Cypher
# ----------------------------------------------------------------------------
Q_USERS = "MATCH (u:User) RETURN u.user_id AS id, u.name AS name ORDER BY id"

Q_RECOMMEND = """
MATCH (me:User {user_id: $user_id})-[:FRIEND_OF]-(friend:User)-[:WATCHED]->(movie:Movie)
WHERE NOT EXISTS { MATCH (me)-[:WATCHED]->(movie) }
RETURN movie.movie_id AS movie_id,
       movie.title AS recommendation,
       count(DISTINCT friend) AS friend_score,
       collect(DISTINCT friend.name) AS friends
ORDER BY friend_score DESC, recommendation
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

Q_FRIEND_MOVIES = """
MATCH (me:User {user_id: $user_id})-[:FRIEND_OF]-(f:User)-[:WATCHED]->(m:Movie)
RETURN f.name AS friend, m.title AS movie ORDER BY friend, movie
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
CALL { MATCH ()-[r:FRIEND_OF]->() RETURN count(r) AS friendships }
CALL { MATCH ()-[r:WATCHED]->() RETURN count(r) AS watches }
RETURN users, movies, friendships, watches
"""


def seed_database() -> None:
    write("CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE")
    write("CREATE CONSTRAINT movie_id_unique IF NOT EXISTS FOR (m:Movie) REQUIRE m.movie_id IS UNIQUE")
    write(
        "UNWIND $rows AS row MERGE (u:User {user_id: row.user_id}) SET u.name = row.name",
        rows=[{"user_id": i, "name": n} for i, n in USERS],
    )
    write(
        "UNWIND $rows AS row MERGE (m:Movie {movie_id: row.movie_id}) SET m.title = row.title",
        rows=[{"movie_id": i, "title": t} for i, t in MOVIES],
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

st.title("🎬 Neo4j Movie Recommendation")
st.caption("แนะนำหนังจากสิ่งที่เพื่อนเคยดู ด้วย Graph Traversal บน Neo4j Aura")

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
    st.subheader("สร้างข้อมูลตัวอย่าง")
    st.write("สร้าง Constraint, User 10 คน, Movie 10 เรื่อง, FRIEND_OF และ WATCHED (ใช้ `MERGE` จึงกดซ้ำได้ไม่เกิดข้อมูลซ้ำ)")
    if st.button("Seed sample data"):
        with st.spinner("กำลังสร้างข้อมูล..."):
            seed_database()
        st.success("เสร็จแล้ว")
        st.rerun()
    counts = run(Q_COUNTS)
    if not counts.empty:
        c = counts.iloc[0]
        cols = st.columns(4)
        cols[0].metric("Users", int(c["users"]))
        cols[1].metric("Movies", int(c["movies"]))
        cols[2].metric("FRIEND_OF", int(c["friendships"]))
        cols[3].metric("WATCHED", int(c["watches"]))

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
# Recommend
# ----------------------------------------------------------------------------
with tab_rec:
    st.subheader(f"หนังที่แนะนำให้ {user_name}")
    rec = run(Q_RECOMMEND, user_id=user_id)
    if rec.empty:
        st.info("ไม่มีหนังแนะนำ — เพื่อนยังไม่ได้ดูหนังที่ผู้ใช้นี้ยังไม่เคยดู หรือยังไม่มีเพื่อน")
    else:
        left, right = st.columns([3, 2])
        with left:
            st.dataframe(
                rec.assign(friends=rec["friends"].map(", ".join)),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "movie_id": "Movie ID",
                    "recommendation": "หนัง",
                    "friend_score": st.column_config.ProgressColumn(
                        "friend_score", min_value=0, max_value=int(rec["friend_score"].max()), format="%d"
                    ),
                    "friends": "เพื่อนที่เคยดู",
                },
            )
        with right:
            st.bar_chart(rec.set_index("recommendation")["friend_score"])
    with st.expander("Cypher ที่ใช้"):
        st.code(Q_RECOMMEND, language="cypher")
    st.caption("friend_score = จำนวนเพื่อนที่เคยดูหนังเรื่องนั้น (กฎแบบง่าย ไม่ใช่โมเดล ML)")

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
    st.markdown("**เพื่อนดูหนังอะไรบ้าง (Alex → Friend → Movie)**")
    st.dataframe(run(Q_FRIEND_MOVIES, user_id=user_id), hide_index=True, use_container_width=True)

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
# Graph (Graphviz ในตัว Streamlit ไม่ต้องติดตั้งเพิ่ม)
# ----------------------------------------------------------------------------
def esc(s: str) -> str:
    return str(s).replace('"', '\\"')


with tab_graph:
    st.subheader(f"Ego graph ของ {user_name}")
    friends = run(Q_FRIENDS, user_id=user_id)
    mine = run(Q_WATCHED, user_id=user_id)
    fm = run(Q_FRIEND_MOVIES, user_id=user_id)
    rec_titles = set(run(Q_RECOMMEND, user_id=user_id).get("recommendation", []))
    mine_titles = set(mine.get("title", []))

    dot = ["digraph G { rankdir=LR; node [style=filled, fontname=Helvetica];"]
    dot.append(f'"me" [label="{esc(user_name)}", shape=circle, fillcolor="#4F8BF9", fontcolor=white];')
    for f in friends.get("friend", []):
        dot.append(f'"f_{esc(f)}" [label="{esc(f)}", shape=circle, fillcolor="#BFD7FF"];')
        dot.append(f'"me" -> "f_{esc(f)}" [label="FRIEND_OF", fontsize=9];')
    movie_nodes = mine_titles | set(fm.get("movie", []))
    for m in movie_nodes:
        color = "#FFD166" if m in rec_titles else ("#B7E4C7" if m in mine_titles else "#EEEEEE")
        dot.append(f'"m_{esc(m)}" [label="{esc(m)}", shape=box, fillcolor="{color}"];')
    for m in mine_titles:
        dot.append(f'"me" -> "m_{esc(m)}" [label="WATCHED", fontsize=9, color="#2D6A4F"];')
    for _, row in fm.iterrows():
        dot.append(f'"f_{esc(row.friend)}" -> "m_{esc(row.movie)}" [label="WATCHED", fontsize=9];')
    dot.append("}")
    st.graphviz_chart("\n".join(dot), use_container_width=True)
    st.caption("🟩 เคยดูแล้ว · 🟨 หนังที่แนะนำ · ⬜ เพื่อนดู แต่ผู้ใช้ยังไม่ดู")
