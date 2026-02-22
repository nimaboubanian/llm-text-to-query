-- ============================================================
-- TPC-H Benchmark Schema for PostgreSQL
-- Based on TPC-H Standard Specification Revision 3.0.1
-- Section 1.4 Table Layouts
-- ============================================================

-- Drop tables if they exist (in reverse dependency order)
DROP TABLE IF EXISTS LINEITEM   CASCADE;
DROP TABLE IF EXISTS ORDERS     CASCADE;
DROP TABLE IF EXISTS PARTSUPP   CASCADE;
DROP TABLE IF EXISTS CUSTOMER   CASCADE;
DROP TABLE IF EXISTS PART       CASCADE;
DROP TABLE IF EXISTS SUPPLIER   CASCADE;
DROP TABLE IF EXISTS NATION     CASCADE;
DROP TABLE IF EXISTS REGION     CASCADE;

-- ============================================================
-- 1. REGION
-- ============================================================
CREATE TABLE REGION (
    R_REGIONKEY  INTEGER         NOT NULL,
    R_NAME       CHAR(25)        NOT NULL,
    R_COMMENT    VARCHAR(152),

    CONSTRAINT pk_region PRIMARY KEY (R_REGIONKEY),
    CONSTRAINT ck_region_key CHECK (R_REGIONKEY >= 0)
);

-- ============================================================
-- 2. NATION
-- ============================================================
CREATE TABLE NATION (
    N_NATIONKEY  INTEGER         NOT NULL,
    N_NAME       CHAR(25)        NOT NULL,
    N_REGIONKEY  INTEGER         NOT NULL,
    N_COMMENT    VARCHAR(152),

    CONSTRAINT pk_nation        PRIMARY KEY (N_NATIONKEY),
    CONSTRAINT fk_nation_region FOREIGN KEY (N_REGIONKEY) REFERENCES REGION (R_REGIONKEY),
    CONSTRAINT ck_nation_key    CHECK (N_NATIONKEY >= 0)
);

-- ============================================================
-- 3. PART
-- ============================================================
CREATE TABLE PART (
    P_PARTKEY     BIGINT          NOT NULL,
    P_NAME        VARCHAR(55)     NOT NULL,
    P_MFGR        CHAR(25)        NOT NULL,
    P_BRAND       CHAR(10)        NOT NULL,
    P_TYPE        VARCHAR(25)     NOT NULL,
    P_SIZE        INTEGER         NOT NULL,
    P_CONTAINER   CHAR(10)        NOT NULL,
    P_RETAILPRICE DECIMAL(15,2)   NOT NULL,
    P_COMMENT     VARCHAR(23)     NOT NULL,

    CONSTRAINT pk_part           PRIMARY KEY (P_PARTKEY),
    CONSTRAINT ck_part_key       CHECK (P_PARTKEY > 0),
    CONSTRAINT ck_part_size      CHECK (P_SIZE > 0),
    CONSTRAINT ck_part_retailprice CHECK (P_RETAILPRICE > 0)
);

-- ============================================================
-- 4. SUPPLIER
-- ============================================================
CREATE TABLE SUPPLIER (
    S_SUPPKEY    BIGINT          NOT NULL,
    S_NAME       CHAR(25)        NOT NULL,
    S_ADDRESS    VARCHAR(40)     NOT NULL,
    S_NATIONKEY  INTEGER         NOT NULL,
    S_PHONE      CHAR(15)        NOT NULL,
    S_ACCTBAL    DECIMAL(15,2)   NOT NULL,
    S_COMMENT    VARCHAR(101)    NOT NULL,

    CONSTRAINT pk_supplier          PRIMARY KEY (S_SUPPKEY),
    CONSTRAINT fk_supplier_nation   FOREIGN KEY (S_NATIONKEY) REFERENCES NATION (N_NATIONKEY),
    CONSTRAINT ck_supplier_key      CHECK (S_SUPPKEY > 0)
);

-- ============================================================
-- 5. CUSTOMER
-- ============================================================
CREATE TABLE CUSTOMER (
    C_CUSTKEY    BIGINT          NOT NULL,
    C_NAME       VARCHAR(25)     NOT NULL,
    C_ADDRESS    VARCHAR(40)     NOT NULL,
    C_NATIONKEY  INTEGER         NOT NULL,
    C_PHONE      CHAR(15)        NOT NULL,
    C_ACCTBAL    DECIMAL(15,2)   NOT NULL,
    C_MKTSEGMENT CHAR(10)        NOT NULL,
    C_COMMENT    VARCHAR(117)    NOT NULL,

    CONSTRAINT pk_customer          PRIMARY KEY (C_CUSTKEY),
    CONSTRAINT fk_customer_nation   FOREIGN KEY (C_NATIONKEY) REFERENCES NATION (N_NATIONKEY),
    CONSTRAINT ck_customer_key      CHECK (C_CUSTKEY > 0)
);

-- ============================================================
-- 6. PARTSUPP
-- ============================================================
CREATE TABLE PARTSUPP (
    PS_PARTKEY     BIGINT          NOT NULL,
    PS_SUPPKEY     BIGINT          NOT NULL,
    PS_AVAILQTY    INTEGER         NOT NULL,
    PS_SUPPLYCOST  DECIMAL(15,2)   NOT NULL,
    PS_COMMENT     VARCHAR(199)    NOT NULL,

    CONSTRAINT pk_partsupp          PRIMARY KEY (PS_PARTKEY, PS_SUPPKEY),
    CONSTRAINT fk_partsupp_part     FOREIGN KEY (PS_PARTKEY) REFERENCES PART     (P_PARTKEY),
    CONSTRAINT fk_partsupp_supplier FOREIGN KEY (PS_SUPPKEY) REFERENCES SUPPLIER (S_SUPPKEY),
    CONSTRAINT ck_partsupp_partkey  CHECK (PS_PARTKEY > 0),
    CONSTRAINT ck_partsupp_suppkey  CHECK (PS_SUPPKEY > 0),
    CONSTRAINT ck_partsupp_availqty CHECK (PS_AVAILQTY > 0),
    CONSTRAINT ck_partsupp_cost     CHECK (PS_SUPPLYCOST > 0)
);

-- ============================================================
-- 7. ORDERS
-- ============================================================
CREATE TABLE ORDERS (
    O_ORDERKEY       BIGINT          NOT NULL,
    O_CUSTKEY        BIGINT          NOT NULL,
    O_ORDERSTATUS    CHAR(1)         NOT NULL,
    O_TOTALPRICE     DECIMAL(15,2)   NOT NULL,
    O_ORDERDATE      DATE            NOT NULL,
    O_ORDERPRIORITY  CHAR(15)        NOT NULL,
    O_CLERK          CHAR(15)        NOT NULL,
    O_SHIPPRIORITY   INTEGER         NOT NULL,
    O_COMMENT        VARCHAR(79)     NOT NULL,

    CONSTRAINT pk_orders            PRIMARY KEY (O_ORDERKEY),
    CONSTRAINT fk_orders_customer   FOREIGN KEY (O_CUSTKEY) REFERENCES CUSTOMER (C_CUSTKEY),
    CONSTRAINT ck_orders_key        CHECK (O_ORDERKEY > 0),
    CONSTRAINT ck_orders_totalprice CHECK (O_TOTALPRICE > 0)
);

-- ============================================================
-- 8. LINEITEM
-- ============================================================
CREATE TABLE LINEITEM (
    L_ORDERKEY       BIGINT          NOT NULL,
    L_PARTKEY        BIGINT          NOT NULL,
    L_SUPPKEY        BIGINT          NOT NULL,
    L_LINENUMBER     INTEGER         NOT NULL,
    L_QUANTITY       DECIMAL(15,2)   NOT NULL,
    L_EXTENDEDPRICE  DECIMAL(15,2)   NOT NULL,
    L_DISCOUNT       DECIMAL(15,2)   NOT NULL,
    L_TAX            DECIMAL(15,2)   NOT NULL,
    L_RETURNFLAG     CHAR(1)         NOT NULL,
    L_LINESTATUS     CHAR(1)         NOT NULL,
    L_SHIPDATE       DATE            NOT NULL,
    L_COMMITDATE     DATE            NOT NULL,
    L_RECEIPTDATE    DATE            NOT NULL,
    L_SHIPINSTRUCT   CHAR(25)        NOT NULL,
    L_SHIPMODE       CHAR(10)        NOT NULL,
    L_COMMENT        VARCHAR(44)     NOT NULL,

    CONSTRAINT pk_lineitem              PRIMARY KEY (L_ORDERKEY, L_LINENUMBER),
    CONSTRAINT fk_lineitem_order        FOREIGN KEY (L_ORDERKEY)              REFERENCES ORDERS   (O_ORDERKEY),
    CONSTRAINT fk_lineitem_part         FOREIGN KEY (L_PARTKEY)               REFERENCES PART     (P_PARTKEY),
    CONSTRAINT fk_lineitem_supplier     FOREIGN KEY (L_SUPPKEY)               REFERENCES SUPPLIER (S_SUPPKEY),
    CONSTRAINT fk_lineitem_partsupp     FOREIGN KEY (L_PARTKEY, L_SUPPKEY)    REFERENCES PARTSUPP (PS_PARTKEY, PS_SUPPKEY),
    CONSTRAINT ck_lineitem_quantity     CHECK (L_QUANTITY > 0),
    CONSTRAINT ck_lineitem_extprice     CHECK (L_EXTENDEDPRICE > 0),
    CONSTRAINT ck_lineitem_discount     CHECK (L_DISCOUNT BETWEEN 0.00 AND 1.00),
    CONSTRAINT ck_lineitem_tax          CHECK (L_TAX >= 0),
    CONSTRAINT ck_lineitem_shipreceipt  CHECK (L_SHIPDATE <= L_RECEIPTDATE)
);

-- ============================================================
-- End of TPC-H Schema
-- ============================================================
