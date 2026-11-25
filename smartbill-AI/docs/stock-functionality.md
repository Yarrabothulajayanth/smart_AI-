# Stock and inventory compatibility

SmartBill's product and billing interface is stock-free:

- Product API requests and frontend product forms do not expose stock fields.
- Checkout does not check or deduct stock and does not create inventory
  movements.
- The frontend contains no inventory controls, low-stock alerts, or stock
  reports.

The existing SQLite database may still contain legacy stock-related columns,
the `inventory_movements` table, and corresponding SQLAlchemy model mappings.
They are retained to preserve compatibility and historic data. This phase
does not drop columns or tables, rewrite existing records, or perform a
destructive migration.

The database schema is therefore intentionally not a reflection of the
stock-free user interface: legacy structures remain unused by the current
product and billing API behavior.
