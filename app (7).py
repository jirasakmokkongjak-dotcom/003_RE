from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import neo4j_service as svc

st.set_page_config(page_title="Library Graph Recommender", page_icon="📚", layout="wide")

NODE_STYLE = {
    "Student": ("#2f6fed", "white"),
    "Book": ("#f2b134", "black"),
    "Category": ("#3aa675", "white"),
    "Author": ("#9b6bd3", "white"),
}


# ---------- cached reads ----------
@st.cache_data(ttl=60, show_spinner=False)
def load_students() -> list[dict]:
    return svc.get_students()


@st.cache_data(ttl=60, show_spinner=False)
def load_books() -> list[dict]:
    return svc.search_books()


@st.cache_data(ttl=60, show_spinner=False)
def load_categories() -> list[str]:
    return svc.list_categories()


def clear_caches() -> None:
    load_students.clear()
    load_books.clear()
    load_categories.clear()


# ---------- helpers ----------
def student_picker(key: str) -> str | None:
    students = load_students()
    if not students:
        return None
    labels = {s["student_id"]: f'{s["name"]} ({s["student_id"]}) · {s["major"]}' for s in students}
    return st.selectbox("นักศึกษา", list(labels), format_func=labels.get, key=key)


def explain(row: dict) -> str:
    parts = []
    if row["friend_count"]:
        names = ", ".join(row["friend_names"])
        parts.append(f"เพื่อน {row['friend_count']} คนเคยยืม ({names})")
    if row["matched_categories"]:
        parts.append("ตรงกับความสนใจ: " + ", ".join(row["matched_categories"]))
    if row["popularity"]:
        parts.append(f"ถูกยืมทั้งหมด {row['popularity']} ครั้ง")
    return " · ".join(parts) or "หนังสือยอดนิยมในห้องสมุด"


def graph_to_dot(rows: list[dict]) -> str:
    nodes: dict[str, tuple[str, str]] = {}
    edges: list[str] = []

    def esc(text: object) -> str:
        return str(text).replace("\\", "\\\\").replace('"', '\\"')

    for r in rows:
        for side in ("source", "target"):
            nodes[r[f"{side}_id"]] = (r[f"{side}_label"], r[f"{side}_name"])
        edges.append(f'"{esc(r["source_id"])}" -> "{esc(r["target_id"])}" [label="{esc(r["relationship"])}", fontsize=9];')

    lines = ["digraph G {", "rankdir=LR;", 'node [shape=box, style="rounded,filled", fontname="Helvetica"];']
    for node_id, (label, name) in nodes.items():
        fill, font = NODE_STYLE.get(label, ("#888888", "white"))
        lines.append(f'"{esc(node_id)}" [label="{esc(name)}", fillcolor="{fill}", fontcolor="{font}"];')
    lines.extend(edges)
    lines.append("}")
    return "\n".join(lines)


# ---------- sidebar ----------
with st.sidebar:
    st.header("การเชื่อมต่อ")
    try:
        connected = svc.ping()
    except Exception as exc:  # noqa: BLE001
        connected = False
        st.error("เชื่อมต่อ Neo4j ไม่ได้ ตรวจสอบค่าใน .streamlit/secrets.toml")
        st.caption(str(exc))
    else:
        st.success("เชื่อมต่อ Neo4j แล้ว")

    if connected and st.button("โหลดข้อมูลตัวอย่าง", help="รันซ้ำได้ ไม่สร้างข้อมูลซ้ำ"):
        with st.spinner("กำลังสร้างข้อมูล..."):
            svc.seed_demo_data()
            clear_caches()
        st.success("โหลดข้อมูลตัวอย่างแล้ว")

if not connected:
    st.stop()

st.title("ระบบแนะนำหนังสือจาก Graph")

tab_dash, tab_rec, tab_search, tab_borrow, tab_graph = st.tabs(
    ["ภาพรวม", "แนะนำหนังสือ", "ค้นหาหนังสือ", "บันทึกการยืม", "กราฟความสัมพันธ์"]
)

# ---------- dashboard ----------
with tab_dash:
    m = svc.get_dashboard_metrics()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("นักศึกษา", m["students"])
    c2.metric("หนังสือ", m["books"])
    c3.metric("การยืม", m["borrows"])
    c4.metric("มิตรภาพ", m["friendships"])
    if not m["students"]:
        st.info("ยังไม่มีข้อมูล กดปุ่ม “โหลดข้อมูลตัวอย่าง” ที่แถบด้านซ้าย")
    else:
        st.subheader("นักศึกษา")
        st.dataframe(pd.DataFrame(load_students()), hide_index=True, use_container_width=True)

# ---------- recommendations ----------
with tab_rec:
    sid = student_picker("rec_student")
    limit = st.slider("จำนวนที่แสดง", 1, 10, 5, key="rec_limit")
    if sid:
        profile = svc.get_profile(sid)
        if profile:
            left, right = st.columns([1, 2])
            with left:
                st.markdown(f"**{profile['name']}** · {profile['major']} ปี {profile['year']}")
                st.write("ความสนใจ: " + (", ".join(profile["interests"]) or "ยังไม่ระบุ"))
                st.write("เคยยืม:")
                for b in profile["borrowed"]:
                    st.write(f"- {b['title']}")
            with right:
                recs = svc.recommend_books(sid, limit)
                if not recs:
                    st.info("ยังไม่มีหนังสือที่แนะนำได้ ลองบันทึกการยืมหรือเพิ่มความสนใจก่อน")
                for r in recs:
                    with st.container(border=True):
                        top, score = st.columns([4, 1])
                        top.markdown(f"**{r['title']}** ({r['year']})")
                        top.caption(f"ผู้แต่ง: {', '.join(r['authors']) or '-'} · หมวด: {', '.join(r['categories']) or '-'}")
                        score.metric("คะแนน", r["score"])
                        st.write(explain(r))

# ---------- search ----------
with tab_search:
    kw_col, cat_col = st.columns([2, 1])
    keyword = kw_col.text_input("ชื่อหนังสือหรือผู้แต่ง", key="search_kw")
    category = cat_col.selectbox("หมวดหมู่", ["ทั้งหมด"] + load_categories(), key="search_cat")
    results = svc.search_books(keyword, None if category == "ทั้งหมด" else category)
    if results:
        df = pd.DataFrame(results)
        df["authors"] = df["authors"].str.join(", ")
        df["categories"] = df["categories"].str.join(", ")
        st.dataframe(df, hide_index=True, use_container_width=True)
    else:
        st.info("ไม่พบหนังสือที่ตรงกับเงื่อนไข ลองเปลี่ยนคำค้นหรือเลือกหมวดหมู่ทั้งหมด")

# ---------- borrow ----------
with tab_borrow:
    books = load_books()
    sid_b = student_picker("borrow_student")
    book_labels = {b["book_id"]: f'{b["title"]} ({b["book_id"]})' for b in books}
    with st.form("borrow_form"):
        book_id = st.selectbox("หนังสือ", list(book_labels), format_func=book_labels.get)
        when = st.date_input("วันที่ยืม", value=date.today())
        rate = st.checkbox("ให้คะแนนหนังสือ")
        rating = st.slider("คะแนน", 1.0, 5.0, 4.0, 0.5)
        submitted = st.form_submit_button("บันทึกการยืม")
    if submitted and sid_b and book_id:
        try:
            svc.record_borrow(sid_b, book_id, when.isoformat(), rating if rate else None)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success("บันทึกการยืมแล้ว")

# ---------- graph ----------
with tab_graph:
    sid_g = student_picker("graph_student")
    size = st.slider("ขนาดกราฟ (จำนวนเส้นทางสูงสุด)", 10, 80, 40, 5)
    if sid_g:
        rows = svc.graph_neighborhood(sid_g, size)
        if rows:
            st.graphviz_chart(graph_to_dot(rows), use_container_width=True)
            st.caption("น้ำเงิน = นักศึกษา · เหลือง = หนังสือ · เขียว = หมวดหมู่")
        else:
            st.info("นักศึกษาคนนี้ยังไม่มีความสัมพันธ์ในกราฟ")
