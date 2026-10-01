from __future__ import annotations

from typing import Any

import streamlit as st
from neo4j import GraphDatabase, RoutingControl


def _config() -> tuple[str, str, str, str]:
    cfg = st.secrets["neo4j"]
    return (
        cfg["uri"],
        cfg["username"],
        cfg["password"],
        cfg.get("database", "neo4j"),
    )


@st.cache_resource(show_spinner=False)
def get_driver():
    """Create one thread-safe Neo4j Driver for the Streamlit process."""
    uri, username, password, _ = _config()
    driver = GraphDatabase.driver(uri, auth=(username, password))
    driver.verify_connectivity()
    return driver


def query(cypher: str, parameters: dict[str, Any] | None = None, *, write: bool = False) -> list[dict[str, Any]]:
    """Execute parameterized Cypher and return rows as dictionaries."""
    _, _, _, database = _config()
    records, _, _ = get_driver().execute_query(
        cypher,
        parameters_=parameters or {},
        database_=database,
        routing_=RoutingControl.WRITE if write else RoutingControl.READ,
    )
    return [record.data() for record in records]


def ping() -> bool:
    rows = query("RETURN 1 AS ok")
    return bool(rows and rows[0]["ok"] == 1)


def get_students() -> list[dict[str, Any]]:
    return query("MATCH (s:Student) RETURN s.student_id AS student_id, s.name AS name, s.major AS major, s.year AS year ORDER BY s.student_id")


def get_dashboard_metrics() -> dict[str, int]:
    rows = query(
        """
        MATCH (s:Student) WITH count(s) AS students
        MATCH (b:Book) WITH students, count(b) AS books
        MATCH ()-[r:BORROWED]->() WITH students, books, count(r) AS borrows
        MATCH ()-[f:FRIEND_OF]->()
        RETURN students, books, borrows, count(f) AS friendships
        """
    )
    return rows[0] if rows else {"students": 0, "books": 0, "borrows": 0, "friendships": 0}


def get_profile(student_id: str) -> dict[str, Any] | None:
    rows = query(
        """
        MATCH (s:Student {student_id:$student_id})
        OPTIONAL MATCH (s)-[:INTERESTED_IN]->(c:Category)
        OPTIONAL MATCH (s)-[:BORROWED]->(b:Book)
        RETURN s.student_id AS student_id, s.name AS name, s.major AS major, s.year AS year,
               collect(DISTINCT c.name) AS interests,
               collect(DISTINCT {book_id:b.book_id, title:b.title}) AS borrowed
        """,
        {"student_id": student_id},
    )
    if not rows:
        return None
    row = rows[0]
    row["borrowed"] = [x for x in row["borrowed"] if x.get("book_id")]
    return row


def recommend_books(student_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Explainable hybrid score: social + interests + popularity + ratings."""
    return query(
        """
        MATCH (u:Student {student_id:$student_id})
        MATCH (b:Book)
        WHERE NOT (u)-[:BORROWED]->(b)

        OPTIONAL MATCH (u)-[:FRIEND_OF]-(f:Student)-[:BORROWED]->(b)
        WITH u, b, count(DISTINCT f) AS friend_count,
             [x IN collect(DISTINCT f.name) WHERE x IS NOT NULL][0..3] AS friend_names

        OPTIONAL MATCH (u)-[:INTERESTED_IN]->(c:Category)<-[:IN_CATEGORY]-(b)
        WITH b, friend_count, friend_names,
             count(DISTINCT c) AS interest_matches,
             [x IN collect(DISTINCT c.name) WHERE x IS NOT NULL] AS matched_categories

        OPTIONAL MATCH (:Student)-[br:BORROWED]->(b)
        WITH b, friend_count, friend_names, interest_matches, matched_categories,
             count(br) AS popularity,
             avg(br.rating) AS avg_rating

        WITH b, friend_count, friend_names, interest_matches, matched_categories,
             popularity, coalesce(avg_rating, 0.0) AS avg_rating,
             (friend_count * 3.0) + (interest_matches * 2.0) +
             (popularity * 0.20) + (coalesce(avg_rating, 0.0) * 0.50) AS score
        WHERE friend_count > 0 OR interest_matches > 0 OR popularity > 0

        OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
        OPTIONAL MATCH (b)-[:IN_CATEGORY]->(allc:Category)
        RETURN b.book_id AS book_id, b.title AS title, b.year AS year,
               collect(DISTINCT a.name) AS authors,
               collect(DISTINCT allc.name) AS categories,
               friend_count, friend_names, interest_matches, matched_categories,
               popularity, round(avg_rating * 100) / 100.0 AS avg_rating,
               round(score * 100) / 100.0 AS score
        ORDER BY score DESC, b.title
        LIMIT $limit
        """,
        {"student_id": student_id, "limit": int(limit)},
    )


def search_books(keyword: str = "", category: str | None = None) -> list[dict[str, Any]]:
    return query(
        """
        MATCH (b:Book)
        OPTIONAL MATCH (a:Author)-[:WROTE]->(b)
        OPTIONAL MATCH (b)-[:IN_CATEGORY]->(c:Category)
        WITH b, collect(DISTINCT a.name) AS authors, collect(DISTINCT c.name) AS categories
        WHERE ($keyword = '' OR toLower(b.title) CONTAINS toLower($keyword)
               OR any(x IN authors WHERE toLower(x) CONTAINS toLower($keyword)))
          AND ($category = '' OR $category IN categories)
        RETURN b.book_id AS book_id, b.title AS title, b.year AS year,
               authors, categories
        ORDER BY b.title
        """,
        {"keyword": keyword.strip(), "category": category or ""},
    )


def list_categories() -> list[str]:
    return [row["name"] for row in query("MATCH (c:Category) RETURN c.name AS name ORDER BY c.name")]


def record_borrow(student_id: str, book_id: str, borrow_date: str, rating: float | None = None) -> None:
    rows = query(
        """
        MATCH (s:Student {student_id:$student_id}), (b:Book {book_id:$book_id})
        MERGE (s)-[r:BORROWED]->(b)
        SET r.borrow_date = date($borrow_date)
        FOREACH (_ IN CASE WHEN $rating IS NULL THEN [] ELSE [1] END | SET r.rating = $rating)
        RETURN count(r) AS saved
        """,
        {"student_id": student_id, "book_id": book_id, "borrow_date": borrow_date, "rating": rating},
        write=True,
    )
    if not rows or rows[0]["saved"] == 0:
        raise ValueError(f"ไม่พบนักศึกษา {student_id} หรือหนังสือ {book_id}")


def graph_neighborhood(student_id: str, limit: int = 40) -> list[dict[str, Any]]:
    return query(
        """
        MATCH (u:Student {student_id:$student_id})
        OPTIONAL MATCH p=(u)-[:FRIEND_OF|BORROWED|INTERESTED_IN*1..2]-()
        WITH p ORDER BY length(p) LIMIT $limit
        UNWIND CASE WHEN p IS NULL THEN [] ELSE relationships(p) END AS r
        WITH DISTINCT r
        WITH startNode(r) AS s, r, endNode(r) AS t
        RETURN elementId(s) AS source_id, labels(s)[0] AS source_label,
               coalesce(s.name, s.title, s.student_id, s.book_id) AS source_name,
               type(r) AS relationship,
               elementId(t) AS target_id, labels(t)[0] AS target_label,
               coalesce(t.name, t.title, t.student_id, t.book_id) AS target_name
        """,
        {"student_id": student_id, "limit": int(limit)},
    )