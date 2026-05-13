import os
from datetime import datetime, UTC

import pandas as pd
import pyodbc
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

SQLSERVER_CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=66.211.150.69;"
    "DATABASE=NHLegislatureDB;"
    "UID=publicuser;"
    "PWD=PublicAccess;"
    "Encrypt=no;"
    "TrustServerCertificate=yes;"
)

POSTGRES_URL = os.getenv(
    "POSTGRES_URL",
    "postgresql+psycopg2://randallnielsen@localhost:5432/nhgc"
)

START_YEAR = int(os.getenv("NHGC_START_YEAR", "2025"))

TABLE_MAPPINGS = [
    ("committees", "committees", None),
    ("docket", "docket", "SessionYear >= ?"),
    ("legislators", "legislators", "SessionYear >= ?"),
    ("sponsors", "sponsors", "SessionYear >= ?"),
    ("rollcallsummary", "rollcallsummary", "SessionYear >= ?"),
    ("rollcallhistory", "rollcallhistory", "SessionYear >= ?"),
    ("houseRemoteTestify", "houseremotetestify", None),
]

COLUMN_RENAMES = {
    "docket": {"DataBase": "database_name"},
    "legislators": {
        "Employeeno": "employeeno",
        "Address": "address",
        "EMailAddress": "emailaddress",
        "Expr1": "expr1",
        "Expr2": "expr2",
        "database": "database_name",
    },
    "sponsors": {
        "employeeNo": "employeeno",
        "PrimeSponsor": "primesponsor",
        "SignedOff": "signedoff",
        "UserName": "username",
        "DateModified": "datemodified",
        "SponsorWithdrawn": "sponsorwithdrawn",
        "LegislationID": "legislationid",
        "PersonID": "personid",
    },
    "rollcallsummary": {
        "VoteSequenceNumber": "votesequencenumber",
        "VoteDate": "votedate",
        "CondensedBillNo": "condensedbillno",
        "Yeas": "yeas",
        "Nays": "nays",
        "Present": "present",
        "Absent": "absent",
        "AbbreviatedTitle1": "abbreviatedtitle1",
        "AbbreviatedTitle2": "abbreviatedtitle2",
        "Question_Motion": "question_motion",
        "Title1": "title1",
        "Title2": "title2",
        "UserName": "username",
        "DateModified": "datemodified",
        "Verified": "verified",
        "CalendarItemID": "calendaritemid",
    },
    "rollcallhistory": {
        "EmployeeNumber": "employeenumber",
        "VoteSequenceNumber": "votesequencenumber",
        "CondensedBillNo": "condensedbillno",
        "Vote": "vote",
        "UserName": "username",
        "DateModified": "datemodified",
        "CalendarItemID": "calendaritemid",
    },
    "houseRemoteTestify": {
        "id": "id",
        "firstName": "firstname",
        "lastName": "lastname",
        "CommitteeDate": "committeedate",
        "committeeID": "committeeid",
        "legislationID": "legislationid",
        "whoIsName": "whoisname",
        "Expr1": "expr1",
        "representing": "representing",
        "Town": "town",
        "State": "state",
        "nonGermane": "nongermane",
        "Expr2": "expr2",
        "TestimonyText": "testimonytext",
    },
    "committees": {
        "CommitteeCode": "committeecode",
        "LongName": "longname",
        "committeename": "committeename",
        "committeeabbreviation": "committeeabbreviation",
        "committeelocation": "committeelocation",
        "CommitteePhone": "committeephone",
        "oldCommitteeSecretary": "oldcommitteesecretary",
        "ActiveCommittee": "activecommittee",
        "CommitteeResearcher": "committeeresearcher",
        "CommitteeSecretary": "committeesecretary",
        "CommitteeAideEmailAddress": "committeeaideemailaddress",
        "CommitteeEmailAddress": "committeeemailaddress",
        "CommitteeID": "committeeid",
        "Database": "database_name",
    },
}

def get_sqlserver_connection():
    return pyodbc.connect(SQLSERVER_CONN_STR, timeout=30)

def get_postgres_engine():
    return create_engine(POSTGRES_URL)

def ensure_schemas(engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS raw;"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS app;"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS raw.sync_log (
                id SERIAL PRIMARY KEY,
                job_name TEXT,
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                status TEXT,
                rows_loaded INTEGER,
                error_message TEXT
            );
        """))

def log_sync(engine, job_name, started_at, finished_at, status, rows_loaded=0, error_message=None):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO raw.sync_log
            (job_name, started_at, finished_at, status, rows_loaded, error_message)
            VALUES
            (:job_name, :started_at, :finished_at, :status, :rows_loaded, :error_message)
        """), {
            "job_name": job_name,
            "started_at": started_at,
            "finished_at": finished_at,
            "status": status,
            "rows_loaded": rows_loaded,
            "error_message": error_message,
        })

def normalize_columns(df, source_table):
    rename_map = COLUMN_RENAMES.get(source_table, {})
    df = df.rename(columns=rename_map)
    df.columns = [c.lower() for c in df.columns]

    boolean_columns_by_table = {
        "committees": ["activecommittee"],
        "legislators": ["active"],
        "sponsors": ["primesponsor", "signedoff", "sponsorwithdrawn"],
        "rollcallsummary": ["verified"],
        "houseremotetestify": ["nongermane"],
    }

    for col in boolean_columns_by_table.get(source_table, []):
        if col in df.columns:
            df[col] = df[col].map(
                lambda x: None if pd.isna(x)
                else bool(int(x)) if isinstance(x, (int, float))
                else bool(x)
            )

    return df

def sync_table(source_table, target_table, where_clause=None):
    started_at = datetime.now(UTC)
    engine = get_postgres_engine()
    job_name = f"sync_{target_table}"

    try:
        sql_conn = get_sqlserver_connection()

        query = f"SELECT * FROM {source_table}"
        params = []

        if where_clause:
            query += f" WHERE {where_clause}"
            params.append(START_YEAR)

        df = pd.read_sql(query, sql_conn, params=params)
        sql_conn.close()

        df = normalize_columns(df, source_table)

        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS raw.{target_table} CASCADE"))

        df.to_sql(
            target_table,
            con=engine,
            schema="raw",
            if_exists="replace",
            index=False,
            method="multi",
            chunksize=1000,
        )

        log_sync(engine, job_name, started_at, datetime.now(UTC), "success", len(df))
        print(f"Synced raw.{target_table}: {len(df)} rows")

    except Exception as e:
        log_sync(engine, job_name, started_at, datetime.now(UTC), "failed", 0, str(e))
        raise

def create_views():
    engine = get_postgres_engine()

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE OR REPLACE VIEW app.bill_latest_status AS
            SELECT DISTINCT ON (sessionyear, legislationid)
                sessionyear,
                lsr,
                legislationid,
                condensedbillno,
                expandedbillno,
                legislativebody,
                description,
                statusdate,
                statusorder
            FROM raw.docket
            WHERE sessionyear >= 2025
            ORDER BY sessionyear, legislationid, statusdate DESC, statusorder DESC;
        """))

        conn.execute(text("""
            CREATE OR REPLACE VIEW app.bill_sponsors AS
            SELECT
                s.sessionyear,
                s.lsr,
                s.legislationid,
                s.primesponsor,
                s.signedoff,
                s.sponsorwithdrawn,
                l.personid,
                l.firstname,
                l.lastname,
                l.party,
                l.legislativebody,
                l.district,
                l.emailaddress
            FROM raw.sponsors s
            LEFT JOIN raw.legislators l
                ON s.personid = l.personid
            WHERE s.sessionyear >= 2025;
        """))

        conn.execute(text("""
            CREATE OR REPLACE VIEW app.legislator_votes AS
            SELECT
                rs.sessionyear,
                rs.condensedbillno,
                rs.votedate,
                rs.question_motion,
                rs.title1,
                rs.title2,
                rh.employeenumber,
                l.firstname,
                l.lastname,
                l.party,
                l.district,
                rh.vote
            FROM raw.rollcallsummary rs
            JOIN raw.rollcallhistory rh
              ON rs.sessionyear = rh.sessionyear
             AND rs.legislativebody = rh.legislativebody
             AND rs.votesequencenumber = rh.votesequencenumber
            LEFT JOIN raw.legislators l
              ON rh.employeenumber = l.employeeno
            WHERE rs.sessionyear >= 2025;
        """))

        conn.execute(text("""
            CREATE OR REPLACE VIEW app.bill_testimony_summary AS
            SELECT
                d.sessionyear,
                d.condensedbillno,
                d.expandedbillno,
                d.legislationid,
                COUNT(*) AS testimony_count,
                COUNT(*) FILTER (WHERE COALESCE(t.nongermane, false) = false) AS germane_count,
                COUNT(*) FILTER (WHERE COALESCE(t.nongermane, false) = true) AS nongermane_count
            FROM raw.houseremotetestify t
            JOIN raw.docket d
              ON t.legislationid = d.legislationid
            WHERE d.sessionyear >= 2025
            GROUP BY d.sessionyear, d.condensedbillno, d.expandedbillno, d.legislationid;
        """))

        conn.execute(text("""
            CREATE OR REPLACE VIEW app.testimony_with_committees AS
            SELECT
                t.id,
                t.firstname,
                t.lastname,
                t.committeedate,
                t.legislationid,
                d.sessionyear,
                d.condensedbillno,
                d.expandedbillno,
                c.committeename,
                c.longname,
                t.representing,
                t.town,
                t.state,
                t.nongermane,
                t.testimonytext
            FROM raw.houseremotetestify t
            LEFT JOIN raw.committees c
              ON t.committeeid = c.committeeid
            LEFT JOIN raw.docket d
              ON t.legislationid = d.legislationid
            WHERE d.sessionyear >= 2025;
        """))

    print("Views created/refreshed.")

if __name__ == "__main__":
    engine = get_postgres_engine()
    ensure_schemas(engine)

    for source_table, target_table, where_clause in TABLE_MAPPINGS:
        sync_table(source_table, target_table, where_clause)

    create_views()