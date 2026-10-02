import os
from datetime import date
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

def write(query: str, **params) -> None:
    st.session_state.driver.execute_query(
        query, parameters_=params, database_=st.session_state.database
    )

# ----------------------------------------------------------------------------
# Cypher Queries
# ----------------------------------------------------------------------------
Q_USERS = "MATCH (u:User) RETURN u.user_id AS id, u.name AS name ORDER BY id"
Q_ALL_MOVIES = "MATCH (m:Movie) RETURN m.movie_id AS id, m.title AS title ORDER BY title"

# 1. แนะนำตามเพื่อนในเครือข่าย
Q_REC_FRIEND = """
MATCH (me:User {user_id: $user_id})-[:FRIEND_OF]-(friend:User)-[:WATCHED]->(movie:Movie)
WHERE NOT EXISTS { MATCH (me)-[:WATCHED]->(movie) }
RETURN movie.movie_id AS movie_id,
       movie.title AS recommendation,
       count(DISTINCT friend) AS score,
       collect(DISTINCT friend.name) AS details
ORDER BY score DESC, recommendation
"""

# 2. แนะนำตามแนวหนังที่ชอบ
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

# 3. แนะนำจากผู้ที่มีรสนิยมคล้ายกัน
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

# 4. แนะนำเพื่อน
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
RETURN m.movie_id AS movie_id, m.title AS title, coalesce(r.rating, '-') AS rating, toString(r.watch_date) AS watch_date
ORDER BY watch_date DESC
"""

Q_FRIENDS = """
MATCH (:User {user_id: $user_id})-[:FRIEND_OF]-(f:User)
RETURN DISTINCT f.user_id AS friend_id, f.name AS friend ORDER BY friend_id
"""

Q_NON_FRIENDS = """
MATCH (me:User {user_id: $user_id}), (other:User)
WHERE me <> other AND NOT (me)-[:FRIEND_OF]-(other)
RETURN other.user_id AS id, other.name AS name ORDER BY id
"""

# Write Queries
Q_ADD_WATCHED = """
MATCH (u:User {user_id: $user_id}), (m:Movie {movie_id: $movie_id})
MERGE (u)-[r:WATCHED]->(m)
SET r.rating = $rating, r.watch_date = date($watch_date)
"""

Q_ADD_FRIEND = """
MATCH (u1:User {user_id: $user_id}), (u2:User {user_id: $friend_id})
MERGE (u1)-[:FRIEND_OF]->(u2)
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

# Sidebar
labels = {r.id: f"{r.id} · {r['name']}" for _, r in users_df.iterrows()}
with st.sidebar:
    st.header("👤 ตัวเลือก")
    user_id = st.selectbox("เลือกผู้ใช้งาน", list(labels), format_func=labels.get)

user_name = users_df.set_index("id").loc[user_id, "name"]

# เพิ่มแท็บใหม่
tab_rec, tab_friend_rec, tab_add_action, tab_search, tab_user, tab_stats = st.tabs(
    [
        "🎯 ระบบแนะนำหนัง",
        "👥 แนะนำเพื่อน",
        "➕ จัดการข้อมูล (ดูหนัง/เพิ่มเพื่อน)",
        "🔍 ค้นหาหนัง",
        "👤 ข้อมูลผู้ใช้",
        "📊 สถิติภาพรวม",
    ]
)

# ----------------------------------------------------------------------------
# 1. Recommend Tab
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
# 2. Friend Recommendation Tab
# ----------------------------------------------------------------------------
with tab_friend_rec:
    st.subheader(f"👥 ระบบแนะนำเพื่อนสำหรับ: {user_name}")
    st.caption("คำนวณจากคนที่มีเพื่อนร่วมกัน (Mutual Friends / Friends of Friends)")
    
    rec_friends = run(Q_REC_FRIEND_SUGGESTION, user_id=user_id)
    
    if rec_friends.empty:
        st.info("ไม่พบคำแนะนำเพื่อนสำหรับผู้ใช้นี้")
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
# 3. Add Actions Tab (เพิ่มประวัติการดูหนัง & เพิ่มเพื่อน) [NEW]
# ----------------------------------------------------------------------------
with tab_add_action:
    col_act1, col_act2 = st.columns(2)
    
    # ฟอร์มเพิ่มการดูหนัง
    with col_act1:
        st.subheader("⭐ บันทึกการรับชมภาพยนตร์")
        movies_df = run(Q_ALL_MOVIES)
        if not movies_df.empty:
            movie_map = {r.id: r.title for _, r in movies_df.iterrows()}
            selected_movie_id = st.selectbox("เลือกภาพยนตร์", list(movie_map.keys()), format_func=lambda x: movie_map[x])
            rating = st.slider("ให้คะแนน (1-5)", 1, 5, 5)
            watch_date = st.date_input("วันที่รับชม", value=date.today())
            
            if st.button("บันทึกการดูหนัง", type="primary"):
                write(Q_ADD_WATCHED, user_id=user_id, movie_id=selected_movie_id, rating=rating, watch_date=str(watch_date))
                st.success(f"บันทึกการดู '{movie_map[selected_movie_id]}' เรียบร้อยแล้ว!")
                st.rerun()

    # ฟอร์มเพิ่มเพื่อน
    with col_act2:
        st.subheader("🤝 เพิ่มเพื่อนใหม่")
        non_friends_df = run(Q_NON_FRIENDS, user_id=user_id)
        if non_friends_df.empty:
            st.info("คุณเป็นเพื่อนกับทุกคนในระบบแล้ว")
        else:
            nf_map = {r.id: f"{r.id} · {r['name']}" for _, r in non_friends_df.iterrows()}
            selected_friend_id = st.selectbox("เลือกคนที่ต้องการเพิ่มเป็นเพื่อน", list(nf_map.keys()), format_func=lambda x: nf_map[x])
            
            if st.button("เพิ่มเพื่อน", type="primary"):
                write(Q_ADD_FRIEND, user_id=user_id, friend_id=selected_friend_id)
                st.success(f"เพิ่มเป็นเพื่อนเรียบร้อยแล้ว!")
                st.rerun()

# ----------------------------------------------------------------------------
# 4. Search Tab (ค้นหาหนัง) [NEW]
# ----------------------------------------------------------------------------
with tab_search:
    st.subheader("🔍 ค้นหาข้อมูลภาพยนตร์")
    search_term = st.text_input("พิมพ์ชื่อภาพยนตร์ที่ต้องการค้นหา:", placeholder="เช่น Matrix, Inception...")
    
    if search_term:
        q_search = """
        MATCH (m:Movie)
        WHERE toLower(m.title) CONTAINS toLower($term)
        OPTIONAL MATCH (u:User)-[r:WATCHED]->(m)
        OPTIONAL MATCH (m)-[:IN_GENRE]->(g:Genre)
        RETURN m.title AS title,
               collect(DISTINCT g.name) AS genres,
               count(DISTINCT u) AS total_watchers,
               avg(r.rating) AS avg_rating,
               collect(DISTINCT u.name) AS watchers
        """
        results = run(q_search, term=search_term)
        if results.empty:
            st.warning("ไม่พบภาพยนตร์ที่ตรงกับคำค้นหา")
        else:
            for _, row in results.iterrows():
                with st.container():
                    st.markdown(f"### 🎬 {row['title']}")
                    st.write(f"**แนวหนัง:** {', '.join(row['genres']) if row['genres'] else 'ไม่ระบุ'}")
                    st.write(f"**จำนวนคนเคยดู:** {row['total_watchers']} คน")
                    avg_r = f"{row['avg_rating']:.1f} ⭐" if row['avg_rating'] else "ยังไม่มีคะแนน"
                    st.write(f"**คะแนนเฉลี่ย:** {avg_r}")
                    if row['watchers']:
                        st.caption(f"ผู้ใช้ที่เคยดูแล้ว: {', '.join(row['watchers'])}")
                    st.divider()

# ----------------------------------------------------------------------------
# 5. User Tab
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
# 6. Stats Tab
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
