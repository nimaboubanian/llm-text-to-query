# TPC-H Data Generator

Generate TPC-H benchmark data using `tpchgen-cli`.

## Database Schema

The TPC-H schema consists of 8 tables representing a business data model:

- **REGION** - Geographic regions (5 records)
- **NATION** - Countries belonging to regions (25 records)
- **SUPPLIER** - Parts suppliers with account balances
- **CUSTOMER** - Customers with market segments and account balances
- **PART** - Parts catalog with brands, types, and retail prices
- **PARTSUPP** - Parts available from suppliers (quantity and cost)
- **ORDERS** - Customer orders with status, dates, and priority
- **LINEITEM** - Individual line items within orders (discounts, taxes, shipping)

The schema includes foreign key relationships: NATION→REGION, SUPPLIER/CUSTOMER→NATION, PARTSUPP→PART/SUPPLIER, ORDERS→CUSTOMER, LINEITEM→ORDERS/PART/SUPPLIER.

## Setup Manually

```bash
# Install uv (if needed)
curl -Ls https://astral.sh/uv/install.sh | sh

# Create environment and install deps
uv venv && uv pip install -r pyproject.toml

# Create data directory
mkdir -p ./data
```

## Generate Data Manually

```bash
# Scale factor 1 (~1 GB)
uv run tpchgen-cli -s 1 --output-dir data/sf1

# Scale factor 10 (~10 GB)
uv run tpchgen-cli -s 10 --output-dir data/sf10
```

## Scale Factors

| Scale | Size    | Time (8-core) |
|-------|---------|---------------|
| 1     | ~1 GB   | ~20 sec       |
| 10    | ~10 GB  | ~2 min        |
| 100   | ~100 GB | ~20 min       |
| 1000  | ~1 TB   | ~2 hours      |
