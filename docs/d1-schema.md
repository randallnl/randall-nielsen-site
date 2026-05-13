randallnielsen@Mac NHdeservesbetter % python3 scripts/sync_nhdb.py schema

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
