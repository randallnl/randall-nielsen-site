import os
import re
import argparse
from datetime import datetime, UTC
from pathlib import Path

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
    "postgresql+psycopg2://randallnielsen@localhost:5432/nhdb"
)

START_SESSION_YEAR = int(os.getenv("START_SESSION_YEAR", "2025"))

EXPORT_DIR = Path("scripts/d1_exports")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

TABLE_MAPPINGS = [
    ("committees", "committees", None),
    ("docket", "docket", "SessionYear"),
    ("legislators", "legislators", None),
    ("sponsors", "sponsors", "SessionYear"),
    ("rollcallsummary", "rollcallsummary", "SessionYear"),
    ("rollcallhistory", "rollcallhistory", "SessionYear"),
    ("houseRemoteTestify", "houseremotetestify", None),
]

COLUMN_RENAMES = {
    "docket": {
        "DataBase": "database_name",
    },
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


def ensure_schemas_and_log_table(engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS raw;"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS app;"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS raw.sync_log (
                id SERIAL PRIMARY KEY,
                job_name TEXT NOT NULL,
                started_at TIMESTAMPTZ NOT NULL,
                finished_at TIMESTAMPTZ NOT NULL,
                status TEXT NOT NULL,
                rows_loaded INTEGER DEFAULT 0,
                error_message TEXT
            );
        """))


def log_sync(engine, job_name, started_at, finished_at, status, rows_loaded=0, error_message=None):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO raw.sync_log (
                job_name,
                started_at,
                finished_at,
                status,
                rows_loaded,
                error_message
            )
            VALUES (
                :job_name,
                :started_at,
                :finished_at,
                :status,
                :rows_loaded,
                :error_message
            )
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
    df.columns = [str(c).lower() for c in df.columns]

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
                lambda x: None
                if pd.isna(x)
                else bool(int(x))
                if isinstance(x, (int, float))
                else str(x).strip().lower() in ["true", "1", "yes", "y"]
            )

    return df


def build_source_query(source_table, year_column):
    if year_column:
        return f"SELECT * FROM {source_table} WHERE {year_column} >= {START_SESSION_YEAR}"

    if source_table == "houseRemoteTestify":
        return f"""
        SELECT t.*
        FROM houseRemoteTestify t
        INNER JOIN docket d
            ON t.legislationID = d.LegislationID
        WHERE d.SessionYear >= {START_SESSION_YEAR}
    """

    return f"SELECT * FROM {source_table}"


def sync_table(source_table, target_table, year_column=None):
    started_at = datetime.now(UTC)
    engine = get_postgres_engine()
    job_name = f"sync_{target_table}"

    try:
        query = build_source_query(source_table, year_column)

        sql_conn = get_sqlserver_connection()
        df = pd.read_sql(query, sql_conn)
        sql_conn.close()

        df = normalize_columns(df, source_table)

        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS raw."{target_table}" CASCADE;'))
            df.head(0).to_sql(
                target_table,
                con=conn,
                schema="raw",
                if_exists="replace",
                index=False,
            )

            if len(df) > 0:
                df.to_sql(
                    target_table,
                    con=conn,
                    schema="raw",
                    if_exists="append",
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
                rs.legislativebody,
                rs.question_motion,
                rs.title1,
                rs.title2,
                rs.yeas,
                rs.nays,
                rs.present,
                rs.absent,
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

        conn.execute(text("""
            CREATE OR REPLACE VIEW app.bills_for_d1 AS
            SELECT
                b.sessionyear,
                b.legislationid,
                b.condensedbillno,
                b.expandedbillno,
                b.legislativebody,
                b.description,
                b.statusdate,
                b.statusorder
            FROM app.bill_latest_status b;
        """))

    print("Views created/refreshed.")


def sql_quote(value):
    if pd.isna(value):
        return "NULL"

    if isinstance(value, bool):
        return "1" if value else "0"

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(int(value)) if float(value).is_integer() else str(value)

    safe = str(value).replace("'", "''")
    return f"'{safe}'"


def bill_filter_clause(bills, columns=None):
    normalized = [b.strip().upper() for b in bills if b.strip()]
    if not normalized:
        raise ValueError("At least one bill number is required.")

    if columns is None:
        columns = ["condensedbillno"]

    bill_list = ", ".join(sql_quote(b) for b in normalized)

    conditions = [
        f"UPPER({column}) IN ({bill_list})"
        for column in columns
    ]

    return " OR ".join(conditions)

def df_to_sqlite_insert(df, table_name):
    if df.empty:
        return f"-- No rows for {table_name}\n"

    columns = list(df.columns)
    col_sql = ", ".join(columns)

    statements = []
    for _, row in df.iterrows():
        values = ", ".join(sql_quote(row[col]) for col in columns)
        statements.append(f"INSERT OR REPLACE INTO {table_name} ({col_sql}) VALUES ({values});")

    return "\n".join(statements) + "\n"

def export_legislator_photos_for_d1(input_csv="scripts/data/legislator_photos.csv", output_file=None):
    if output_file is None:
        output_file = EXPORT_DIR / "d1_legislator_photos.sql"
    else:
        output_file = Path(output_file)

    df = pd.read_csv(input_csv)

    required = [
        "employeeno",
        "personid",
        "firstname",
        "lastname",
        "filename",
        "photo_url",
        "source",
    ]

    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in photo CSV: {missing}")

    parts = [
        "-- D1 legislator photo import generated by sync_nhdb.py",
        f"-- Generated at {datetime.now(UTC).isoformat()}",
        "",
        "DELETE FROM d1_legislator_photos;",
        "",
        df_to_sqlite_insert(df, "d1_legislator_photos"),
    ]

    output_file.write_text("\n".join(parts), encoding="utf-8")
    print(f"Created D1 legislator photo SQL: {output_file}")
    print(f"Photos exported: {len(df)}")

    return output_file

def export_district_mapping_for_d1(
    input_csv="scripts/data/district_community_mapping.csv",
    output_file=None
):
    if output_file is None:
        output_file = EXPORT_DIR / "d1_district_mapping.sql"
    else:
        output_file = Path(output_file)

    df = pd.read_csv(input_csv)

    required = [
        "body",
        "county",
        "district",
        "district_label",
        "communities_represented",
    ]

    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in district mapping CSV: {missing}")

    df["body"] = df["body"].astype(str).str.strip().str.upper()
    df["district_label"] = df["district_label"].astype(str).str.strip()
    df["communities_represented"] = df["communities_represented"].astype(str).str.strip()

    df = df[df["body"].isin(["H", "S"])]
    df = df[df["district_label"] != ""]
    df = df[df["communities_represented"] != ""]

    df["county"] = pd.to_numeric(df["county"], errors="coerce").astype("Int64")
    df["district"] = pd.to_numeric(df["district"], errors="coerce").astype("Int64")

    df = df.dropna(subset=["district"])
    df = df.drop_duplicates(subset=["body", "county", "district"], keep="last")

    parts = [
        "-- D1 district mapping import generated by sync_nhdb.py",
        f"-- Generated at {datetime.now(UTC).isoformat()}",
        "",
        "DELETE FROM d1_district_mapping;",
        "",
        df_to_sqlite_insert(df, "d1_district_mapping"),
    ]

    output_file.write_text("\n".join(parts), encoding="utf-8")

    print(f"Created D1 district mapping SQL: {output_file}")
    print(f"District mappings exported: {len(df)}")

    return output_file


def export_legislators_for_d1(output_file=None):
    engine = get_postgres_engine()

    if output_file is None:
        output_file = EXPORT_DIR / "d1_legislators.sql"
    else:
        output_file = Path(output_file)

    query = """

    SELECT
        personid,
        employeeno,
        firstname,
        lastname,
        middlename,
        legislativebody,
        active,
        seatno,
        countycode,
        district,
        party,
        address,
        address2,
        city,
        zipcode,
        emailaddress,
        gendercode,
        secretaryid,
        database_name
    FROM raw.legislators
    WHERE active = true
    ORDER BY legislativebody, lastname, firstname;
    """

    df = pd.read_sql(text(query), engine)

    parts = [
        "-- D1 legislator import generated by sync_nhdb.py",
        f"-- Generated at {datetime.now(UTC).isoformat()}",
        "",
        "DELETE FROM d1_legislators;",
        "",
        df_to_sqlite_insert(df, "d1_legislators"),
    ]

    output_file.write_text("\n".join(parts), encoding="utf-8")
    print(f"Created D1 legislator SQL: {output_file}")
    print(f"Legislators exported: {len(df)}")

    return output_file

def export_selected_bills_for_d1(bills, output_file=None):
    engine = get_postgres_engine()
    bill_where_docket = bill_filter_clause(bills, ["condensedbillno", "expandedbillno"])
    bill_where_rollcall = bill_filter_clause(bills, ["condensedbillno"])
    bill_where_testimony = bill_filter_clause(bills, ["condensedbillno", "expandedbillno"])

    if output_file is None:
        safe_name = "_".join(re.sub(r"[^A-Za-z0-9]+", "", b.upper()) for b in bills)
        output_file = EXPORT_DIR / f"d1_selected_bills_{safe_name}.sql"
    else:
        output_file = Path(output_file)

    queries = {
    "d1_bills": f"""
        SELECT
            sessionyear,
            legislationid,
            condensedbillno,
            expandedbillno,
            legislativebody,
            description,
            statusdate,
            statusorder
        FROM app.bills_for_d1
        WHERE {bill_where_docket}
        ORDER BY sessionyear, condensedbillno;
    """,

    "d1_rollcallsummary": f"""
        SELECT
            rs.sessionyear,
            rs.legislativebody,
            rs.votesequencenumber,
            rs.votedate,
            rs.condensedbillno,
            rs.yeas,
            rs.nays,
            rs.present,
            rs.absent,
            rs.question_motion,
            rs.title1,
            rs.title2,
            rs.verified,
            rs.calendaritemid
        FROM raw.rollcallsummary rs
        WHERE {bill_where_rollcall}
        ORDER BY rs.sessionyear, rs.votedate, rs.votesequencenumber;
    """,

    "d1_rollcallhistory": f"""
        SELECT
            rh.sessionyear,
            rh.legislativebody,
            rh.votesequencenumber,
            rh.employeenumber,
            rh.condensedbillno,
            rh.vote,
            rh.calendaritemid
        FROM raw.rollcallhistory rh
        WHERE {bill_where_rollcall}
        ORDER BY rh.sessionyear, rh.votesequencenumber, rh.employeenumber;
    """,

    "d1_testimony": f"""
        SELECT
            t.id,
            t.firstname,
            t.lastname,
            t.committeedate,
            t.legislationid,
            t.sessionyear,
            t.condensedbillno,
            t.expandedbillno,
            t.committeename,
            t.longname,
            t.representing,
            t.town,
            t.state,
            t.nongermane,
            t.testimonytext
        FROM app.testimony_with_committees t
        WHERE {bill_where_testimony}
        ORDER BY t.committeedate, t.lastname, t.firstname;
    """,
}

    parts = [
    "-- D1 import generated by sync_nhdb.py",
    f"-- Generated at {datetime.now(UTC).isoformat()}",
    f"-- Bills: {', '.join(bills)}",
    "",
]
    
    for table_name, query in queries.items():
        df = pd.read_sql(text(query), engine)
        parts.append(f"-- Refresh {table_name}")
        if table_name in ["d1_rollcallsummary", "d1_rollcallhistory"]:
            delete_where = bill_where_rollcall
        elif table_name == "d1_testimony":
            delete_where = bill_where_testimony
        else:
            delete_where = bill_where_docket
                    
        parts.append(f"DELETE FROM {table_name} WHERE {delete_where};")
        
        parts.append(df_to_sqlite_insert(df, table_name))
        
        parts.append("")



    output_file.write_text("\n".join(parts), encoding="utf-8")
    print(f"Created D1 import SQL: {output_file}")

    return output_file


def print_d1_schema():
    print("""
Run this in Cloudflare D1 before importing selected bill data:

CREATE TABLE IF NOT EXISTS d1_bills (
  sessionyear INTEGER,
  legislationid INTEGER,
  condensedbillno TEXT,
  expandedbillno TEXT,
  legislativebody TEXT,
  description TEXT,
  statusdate TEXT,
  statusorder INTEGER,
  PRIMARY KEY (sessionyear, legislationid)
);

CREATE TABLE IF NOT EXISTS d1_rollcallsummary (
  sessionyear INTEGER,
  legislativebody TEXT,
  votesequencenumber INTEGER,
  votedate TEXT,
  condensedbillno TEXT,
  yeas INTEGER,
  nays INTEGER,
  present INTEGER,
  absent INTEGER,
  question_motion TEXT,
  title1 TEXT,
  title2 TEXT,
  verified INTEGER,
  calendaritemid INTEGER,
  PRIMARY KEY (sessionyear, legislativebody, votesequencenumber)
);

CREATE TABLE IF NOT EXISTS d1_rollcallhistory (
  sessionyear INTEGER,
  legislativebody TEXT,
  votesequencenumber INTEGER,
  employeenumber INTEGER,
  condensedbillno TEXT,
  vote TEXT,
  calendaritemid INTEGER,
  PRIMARY KEY (sessionyear, legislativebody, votesequencenumber, employeenumber)
);

CREATE TABLE IF NOT EXISTS d1_testimony (
  id INTEGER PRIMARY KEY,
  firstname TEXT,
  lastname TEXT,
  committeedate TEXT,
  legislationid INTEGER,
  sessionyear INTEGER,
  condensedbillno TEXT,
  expandedbillno TEXT,
  committeename TEXT,
  longname TEXT,
  representing TEXT,
  town TEXT,
  state TEXT,
  nongermane INTEGER,
  testimonytext TEXT
);
""")

def inspect_source_columns():
    sql_conn = get_sqlserver_connection()

    for source_table, target_table, year_column in TABLE_MAPPINGS:
        print(f"\n--- {source_table} ---")
        df = pd.read_sql(f"""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = '{source_table}'
            ORDER BY ORDINAL_POSITION
        """, sql_conn)

        print(df["COLUMN_NAME"].to_list())

    sql_conn.close()


def sync_all():
    engine = get_postgres_engine()
    ensure_schemas_and_log_table(engine)

    for source_table, target_table, year_column in TABLE_MAPPINGS:
        sync_table(source_table, target_table, year_column)

    create_views()


def main():
    parser = argparse.ArgumentParser(description="NH Deserves Better General Court sync tool")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("sync", help="Sync 2025-current General Court data to local Postgres")
    subparsers.add_parser("inspect", help="Inspect source SQL Server table columns")
    subparsers.add_parser("schema", help="Print D1 schema for selected bill imports")
    subparsers.add_parser("export-legislators", help="Export active legislators to D1-ready SQL")

    export_parser = subparsers.add_parser("export-bills", help="Export selected bills to D1-ready SQL")
    export_parser.add_argument("bills", nargs="+", help="Bill numbers, e.g. HB699 SB272")
    export_parser.add_argument("--out", help="Optional output file path")

    photo_parser = subparsers.add_parser(
    "export-legislator-photos",
    help="Export legislator photo mappings to D1-ready SQL"
    )
    
    photo_parser.add_argument(
    "--input",
    default="scripts/data/legislator_photos.csv",
    help="Path to legislator photo CSV"
    )

    district_parser = subparsers.add_parser(
    "export-district-mapping",
    help="Export district-to-community mapping to D1-ready SQL"
    )
    
    district_parser.add_argument(
    "--input",
    default="scripts/data/district_community_mapping.csv",
    help="Path to district mapping CSV"
    )
    
    args = parser.parse_args()

    if args.command == "sync":
        sync_all()
    elif args.command == "inspect":
        inspect_source_columns()
    elif args.command == "schema":
        print_d1_schema()
    elif args.command == "export-bills":
        export_selected_bills_for_d1(args.bills, args.out)
    elif args.command == "export-legislators":
        export_legislators_for_d1()
    elif args.command == "export-legislator-photos":
        export_legislator_photos_for_d1(args.input)
    elif args.command == "export-district-mapping":
        export_district_mapping_for_d1(args.input)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()