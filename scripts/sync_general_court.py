import os
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
    "postgresql+psycopg2://randallnielsen@localhost:5432/nhgc"
)

OUTPUT_DIR = Path("scripts/d1_exports")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TABLE_MAPPINGS = [
    ("committees", "committees"),
    ("docket", "docket"),
    ("legislators", "legislators"),
    ("sponsors", "sponsors"),
    ("rollcallsummary", "rollcallsummary"),
    ("rollcallhistory", "rollcallhistory"),
    ("houseRemoteTestify", "houseremotetestify"),
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


def ensure_local_schema():
    engine = get_postgres_engine()

    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS raw;"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS app;"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS raw.sync_log (
                id SERIAL PRIMARY KEY,
                job_name TEXT NOT NULL,
                started_at TIMESTAMP NOT NULL,
                finished_at TIMESTAMP NOT NULL,
                status TEXT NOT NULL,
                rows_loaded INTEGER DEFAULT 0,
                error_message TEXT
            );
        """))

    print("Local schemas ready.")


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
    df.columns = [c.lower() for c in df.columns]

    boolean_columns_by_table = {
        "committees": ["activecommittee"],
        "legislators": ["active"],
        "sponsors": ["primesponsor", "signedoff", "sponsorwithdrawn"],
        "rollcallsummary": ["verified"],
        "houseRemoteTestify": ["nongermane"],
        "houseremotetestify": ["nongermane"],
    }

    for col in boolean_columns_by_table.get(source_table, []):
        if col in df.columns:
            df[col] = df[col].map(normalize_bool)

    return df


def normalize_bool(value):
    if pd.isna(value):
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(int(value))

    value_string = str(value).strip().lower()

    if value_string in ["1", "true", "t", "yes", "y"]:
        return True

    if value_string in ["0", "false", "f", "no", "n"]:
        return False

    return bool(value)


def sync_full_table(source_table, target_table):
    started_at = datetime.now(UTC).replace(tzinfo=None)
    engine = get_postgres_engine()
    job_name = f"sync_{target_table}"

    try:
        sql_conn = get_sqlserver_connection()
        df = pd.read_sql(f"SELECT * FROM {source_table}", sql_conn)
        sql_conn.close()

        df = normalize_columns(df, source_table)
        
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE TABLE raw.{target_table} RESTART IDENTITY CASCADE;"))
            df.to_sql(
                target_table,
                con=engine,
                schema="raw",
                if_exists="append",
                index=False,
                method="multi",
                chunksize=1000,
                )

        finished_at = datetime.now(UTC).replace(tzinfo=None)
        log_sync(engine, job_name, started_at, finished_at, "success", len(df))
        print(f"Synced raw.{target_table}: {len(df)} rows")

    except Exception as e:
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        log_sync(engine, job_name, started_at, finished_at, "failed", 0, str(e))
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
                ON s.personid = l.personid;
        """))

        conn.execute(text("""
            CREATE OR REPLACE VIEW app.legislator_votes AS
            SELECT
                rs.sessionyear,
                rs.legislativebody,
                rs.condensedbillno,
                rs.votedate,
                rs.question_motion,
                rs.title1,
                rs.title2,
                rs.votesequencenumber,
                rh.employeenumber,
                l.personid,
                l.firstname,
                l.lastname,
                l.party,
                l.legislativebody AS legislator_body,
                l.district,
                l.emailaddress,
                rh.vote
            FROM raw.rollcallsummary rs
            JOIN raw.rollcallhistory rh
              ON rs.sessionyear = rh.sessionyear
             AND rs.legislativebody = rh.legislativebody
             AND rs.votesequencenumber = rh.votesequencenumber
            LEFT JOIN raw.legislators l
              ON rh.employeenumber = l.employeeno;
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
            GROUP BY d.sessionyear, d.condensedbillno, d.expandedbillno, d.legislationid;
        """))

        conn.execute(text("""
            CREATE OR REPLACE VIEW app.testimony_with_committees AS
            SELECT
                t.id,
                t.firstname,
                t.lastname,
                t.committeedate,
                t.committeeid,
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
              ON t.legislationid = d.legislationid;
        """))

        conn.execute(text("""
            CREATE OR REPLACE VIEW app.bill_rollcalls AS
            SELECT
                rs.sessionyear,
                rs.legislativebody,
                rs.condensedbillno,
                rs.votedate,
                rs.votesequencenumber,
                rs.question_motion,
                rs.title1,
                rs.title2,
                rs.yeas,
                rs.nays,
                rs.present,
                rs.absent,
                rs.verified
            FROM raw.rollcallsummary rs;
        """))

    print("Views created/refreshed.")


def sql_quote(value):
    if value is None or pd.isna(value):
        return "NULL"

    if isinstance(value, bool):
        return "1" if value else "0"

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(int(value)) if float(value).is_integer() else str(value)

    value = str(value)
    value = value.replace("'", "''")
    return f"'{value}'"


def dataframe_to_insert_sql(df, table_name, delete_where=None):
    if df.empty:
        return f"-- No rows for {table_name}\n"

    columns = list(df.columns)
    column_sql = ", ".join(columns)

    statements = []

    if delete_where:
        statements.append(f"DELETE FROM {table_name} WHERE {delete_where};")
    else:
        statements.append(f"DELETE FROM {table_name};")

    for _, row in df.iterrows():
        values = ", ".join(sql_quote(row[col]) for col in columns)
        statements.append(f"INSERT INTO {table_name} ({column_sql}) VALUES ({values});")

    return "\n".join(statements) + "\n"


def create_d1_schema_file():
    schema = """
CREATE TABLE IF NOT EXISTS bills (
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

CREATE TABLE IF NOT EXISTS rollcall_summary (
  sessionyear INTEGER,
  legislativebody TEXT,
  condensedbillno TEXT,
  votedate TEXT,
  votesequencenumber INTEGER,
  question_motion TEXT,
  title1 TEXT,
  title2 TEXT,
  yeas INTEGER,
  nays INTEGER,
  present INTEGER,
  absent INTEGER,
  verified INTEGER,
  PRIMARY KEY (sessionyear, legislativebody, votesequencenumber)
);

CREATE TABLE IF NOT EXISTS rollcall_votes (
  sessionyear INTEGER,
  legislativebody TEXT,
  condensedbillno TEXT,
  votedate TEXT,
  votesequencenumber INTEGER,
  employeenumber INTEGER,
  personid INTEGER,
  firstname TEXT,
  lastname TEXT,
  party TEXT,
  legislator_body TEXT,
  district TEXT,
  emailaddress TEXT,
  vote TEXT,
  PRIMARY KEY (sessionyear, legislativebody, votesequencenumber, employeenumber)
);

CREATE TABLE IF NOT EXISTS testimony (
  id INTEGER PRIMARY KEY,
  firstname TEXT,
  lastname TEXT,
  committeedate TEXT,
  committeeid INTEGER,
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

CREATE TABLE IF NOT EXISTS testimony_summary (
  sessionyear INTEGER,
  condensedbillno TEXT,
  expandedbillno TEXT,
  legislationid INTEGER,
  testimony_count INTEGER,
  germane_count INTEGER,
  nongermane_count INTEGER,
  PRIMARY KEY (sessionyear, legislationid)
);

CREATE TABLE IF NOT EXISTS bill_overrides (
  sessionyear INTEGER,
  condensedbillno TEXT,
  public_title TEXT,
  plain_language_summary TEXT,
  issue_area TEXT,
  stance TEXT,
  priority_level TEXT,
  action_note TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (sessionyear, condensedbillno)
);

CREATE TABLE IF NOT EXISTS vote_overrides (
  sessionyear INTEGER,
  condensedbillno TEXT,
  votesequencenumber INTEGER,
  preferred_vote TEXT,
  explanation TEXT,
  issue_area TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (sessionyear, condensedbillno, votesequencenumber)
);
""".strip()

    out = OUTPUT_DIR / "d1_schema.sql"
    out.write_text(schema)
    print(f"Wrote {out}")


def export_selected_bills_to_d1_sql(bills):
    if not bills:
        raise ValueError("No bills provided. Use --bills HB123 SB456 or set FEATURED_BILLS in .env.")

    engine = get_postgres_engine()

    bills = [bill.upper().strip() for bill in bills]
    bill_placeholders = ", ".join([f":bill_{i}" for i in range(len(bills))])
    params = {f"bill_{i}": bill for i, bill in enumerate(bills)}

    with engine.begin() as conn:
        bill_df = pd.read_sql(
            text(f"""
                SELECT
                    sessionyear,
                    legislationid,
                    condensedbillno,
                    expandedbillno,
                    legislativebody,
                    description,
                    statusdate::text AS statusdate,
                    statusorder
                FROM app.bill_latest_status
                WHERE UPPER(condensedbillno) IN ({bill_placeholders})
                   OR UPPER(expandedbillno) IN ({bill_placeholders})
                ORDER BY sessionyear DESC, condensedbillno;
            """),
            conn,
            params=params,
        )

        rollcall_summary_df = pd.read_sql(
            text(f"""
                SELECT
                    sessionyear,
                    legislativebody,
                    condensedbillno,
                    votedate::text AS votedate,
                    votesequencenumber,
                    question_motion,
                    title1,
                    title2,
                    yeas,
                    nays,
                    present,
                    absent,
                    verified
                FROM app.bill_rollcalls
                WHERE UPPER(condensedbillno) IN ({bill_placeholders})
                ORDER BY sessionyear DESC, condensedbillno, votedate, votesequencenumber;
            """),
            conn,
            params=params,
        )

        rollcall_votes_df = pd.read_sql(
            text(f"""
                SELECT
                    sessionyear,
                    legislativebody,
                    condensedbillno,
                    votedate::text AS votedate,
                    votesequencenumber,
                    employeenumber,
                    personid,
                    firstname,
                    lastname,
                    party,
                    legislator_body,
                    district,
                    emailaddress,
                    vote
                FROM app.legislator_votes
                WHERE UPPER(condensedbillno) IN ({bill_placeholders})
                ORDER BY sessionyear DESC, condensedbillno, votedate, votesequencenumber, lastname, firstname;
            """),
            conn,
            params=params,
        )

        testimony_df = pd.read_sql(
            text(f"""
                SELECT
                    id,
                    firstname,
                    lastname,
                    committeedate::text AS committeedate,
                    committeeid,
                    legislationid,
                    sessionyear,
                    condensedbillno,
                    expandedbillno,
                    committeename,
                    longname,
                    representing,
                    town,
                    state,
                    nongermane,
                    testimonytext
                FROM app.testimony_with_committees
                WHERE UPPER(condensedbillno) IN ({bill_placeholders})
                   OR UPPER(expandedbillno) IN ({bill_placeholders})
                ORDER BY sessionyear DESC, condensedbillno, committeedate, lastname, firstname;
            """),
            conn,
            params=params,
        )

        testimony_summary_df = pd.read_sql(
            text(f"""
                SELECT
                    sessionyear,
                    condensedbillno,
                    expandedbillno,
                    legislationid,
                    testimony_count,
                    germane_count,
                    nongermane_count
                FROM app.bill_testimony_summary
                WHERE UPPER(condensedbillno) IN ({bill_placeholders})
                   OR UPPER(expandedbillno) IN ({bill_placeholders})
                ORDER BY sessionyear DESC, condensedbillno;
            """),
            conn,
            params=params,
        )

    bill_list_sql = ", ".join(sql_quote(bill) for bill in bills)

    output_sql = []
    output_sql.append("-- Generated by scripts/sync_general_court.py")
    output_sql.append(f"-- Generated at {datetime.now(UTC).isoformat()}")
    output_sql.append(f"-- Bills: {', '.join(bills)}")
    output_sql.append("")

    output_sql.append(dataframe_to_insert_sql(
        bill_df,
        "bills",
        delete_where=f"UPPER(condensedbillno) IN ({bill_list_sql}) OR UPPER(expandedbillno) IN ({bill_list_sql})"
    ))

    output_sql.append(dataframe_to_insert_sql(
        rollcall_summary_df,
        "rollcall_summary",
        delete_where=f"UPPER(condensedbillno) IN ({bill_list_sql})"
    ))

    output_sql.append(dataframe_to_insert_sql(
        rollcall_votes_df,
        "rollcall_votes",
        delete_where=f"UPPER(condensedbillno) IN ({bill_list_sql})"
    ))

    output_sql.append(dataframe_to_insert_sql(
        testimony_df,
        "testimony",
        delete_where=f"UPPER(condensedbillno) IN ({bill_list_sql}) OR UPPER(expandedbillno) IN ({bill_list_sql})"
    ))

    output_sql.append(dataframe_to_insert_sql(
        testimony_summary_df,
        "testimony_summary",
        delete_where=f"UPPER(condensedbillno) IN ({bill_list_sql}) OR UPPER(expandedbillno) IN ({bill_list_sql})"
    ))

    out = OUTPUT_DIR / "selected_bills_import.sql"
    out.write_text("\n".join(output_sql))

    print(f"Wrote {out}")
    print(f"Bills exported: {', '.join(bills)}")
    print(f"Bill rows: {len(bill_df)}")
    print(f"Roll call summary rows: {len(rollcall_summary_df)}")
    print(f"Roll call vote rows: {len(rollcall_votes_df)}")
    print(f"Testimony rows: {len(testimony_df)}")
    print(f"Testimony summary rows: {len(testimony_summary_df)}")


def parse_bills(args):
    if args.bills:
        return args.bills

    env_bills = os.getenv("FEATURED_BILLS", "")
    if env_bills.strip():
        return [bill.strip() for bill in env_bills.split(",") if bill.strip()]

    return []


def main():
    parser = argparse.ArgumentParser(description="Sync NH General Court data locally and export selected bills for Cloudflare D1.")

    parser.add_argument(
        "--sync",
        action="store_true",
        help="Sync all configured General Court tables into local Postgres."
    )

    parser.add_argument(
        "--views",
        action="store_true",
        help="Create or refresh local app views."
    )

    parser.add_argument(
        "--schema",
        action="store_true",
        help="Generate D1 schema SQL file."
    )

    parser.add_argument(
        "--export-d1",
        action="store_true",
        help="Export selected bills as D1-ready SQL."
    )

    parser.add_argument(
        "--bills",
        nargs="*",
        help="Bill numbers to export, such as HB699 SB295."
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Run sync, refresh views, generate schema, and export selected bills."
    )

    args = parser.parse_args()

    if args.all:
        args.sync = True
        args.views = True
        args.schema = True
        args.export_d1 = True

    ensure_local_schema()

    if args.sync:
        for source_table, target_table in TABLE_MAPPINGS:
            sync_full_table(source_table, target_table)

    if args.views:
        create_views()

    if args.schema:
        create_d1_schema_file()

    if args.export_d1:
        bills = parse_bills(args)
        export_selected_bills_to_d1_sql(bills)

    if not any([args.sync, args.views, args.schema, args.export_d1]):
        print("Nothing to do. Try:")
        print("python3 scripts/sync_general_court.py --all --bills HB699 SB295")
        print("python3 scripts/sync_general_court.py --sync --views")
        print("python3 scripts/sync_general_court.py --export-d1 --bills HB699")


if __name__ == "__main__":
    main()