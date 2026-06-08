# Semantic Model Inventory

A Microsoft Fabric notebook that performs a **tenant-wide scan** of all Power BI semantic models (datasets) and classifies them by storage mode, identifying the underlying data source for each.

## What It Does

This notebook uses the **Power BI Admin Scanner API** to enumerate every semantic model across all workspaces in your Fabric tenant and produces a comprehensive inventory with:

| Column | Description |
|--------|-------------|
| `workspace_name` | Workspace containing the semantic model |
| `workspace_id` | Workspace GUID |
| `dataset_name` | Semantic model display name |
| `dataset_id` | Semantic model GUID |
| `storage_mode` | Classification (see below) |
| `content_provider_type` | Raw `contentProviderType` from Scanner API |
| `table_storage_modes` | Distinct `storageMode` values at the table level |
| `source_type` | Resolved item type (Lakehouse, Warehouse, etc.) |
| `source_item_id` | GUID of the source item |
| `source_item_name` | Display name of the source item |
| `source_workspace_id` | Workspace where the source item resides |
| `expression_snippet` | First 200 chars of the M expression (for validation) |

### Storage Mode Classification

| Classification | How It's Determined |
|---------------|-------------------|
| **Direct Lake on OneLake** | Tables have `storageMode = "DirectLake"` and expression references an `abfss://` OneLake path |
| **Direct Lake on SQL** | Tables have `storageMode = "DirectLake"` and expression uses `Sql.Database()` pointing to a Fabric SQL endpoint |
| **Import** | All tables have `storageMode = "Import"` |
| **DirectQuery** | All tables have `storageMode = "DirectQuery"` |
| **Composite** | Mix of Import + DirectQuery tables, or `contentProviderType` indicates composite mode |

### Source Item Resolution

For Direct Lake models, the notebook:
1. Parses M expressions to extract server URLs and database identifiers
2. Detects when the database value is a GUID (vs. a display name)
3. Calls the **Fabric Items API** (`GET /v1/workspaces/{wsId}/items/{itemId}`) to resolve the actual item type and display name
4. This reliably distinguishes **Lakehouse** from **Warehouse** (both use `.datawarehouse.fabric.microsoft.com` URLs)

## Authentication Options

### Option 1: Run as Current User (Interactive)

The simplest approach — uses the notebook's identity token.

**Requirements:**
- User must have **Fabric Administrator** role OR **Power BI Service Administrator** role (assigned in Microsoft 365 Admin Center)
- The user's identity is used for both the Scanner API and the Fabric Items API

### Option 2: Run as Service Principal (SPN)

Best for scheduled/automated runs.

**Setup Steps:**
1. Register an application in **Microsoft Entra ID** (Azure AD)
2. Create a **Client Secret** (or certificate) for the app
3. Create a **Security Group** in Entra ID and add the SPN as a member
4. In **Power BI Admin Portal → Tenant Settings**, enable these for the security group:
   - ✅ *Allow service principals to use Power BI APIs*
   - ✅ *Allow service principals to use read-only admin APIs*
   - ✅ *Enhance admin APIs responses with detailed metadata*
   - ✅ *Enhance admin APIs responses with DAX and mashup expressions*
5. Store credentials in **Azure Key Vault** (recommended) or pass via notebook parameters

> **Note:** The SPN does NOT need workspace-level permissions — Admin Scanner APIs are tenant-scoped.

## Tenant Settings (Required for Both Options)

In **Power BI Admin Portal → Tenant Settings**, ensure these are **Enabled**:

| Setting | Why |
|---------|-----|
| Enhance admin APIs responses with detailed metadata | Required to get table-level `storageMode` |
| Enhance admin APIs responses with DAX and mashup expressions | Required to retrieve dataset M expressions (reveals source paths) |

## How to Use

1. Import the notebook into a Microsoft Fabric workspace
2. Attach a Lakehouse (for default Spark session)
3. In **Cell 1**, set `auth_mode`:
   ```python
   auth_mode = "user"   # or "spn"
   ```
4. If using SPN, configure credentials in Cell 1 (Key Vault or direct)
5. Run all cells
6. Review the output DataFrame displayed in the final cell

## API Flow

```
┌─────────────────────────────────────────────────────────┐
│  1. GET /admin/workspaces/modified                       │
│     → List of all workspace IDs                          │
├─────────────────────────────────────────────────────────┤
│  2. POST /admin/workspaces/getInfo (batches of 100)      │
│     params: datasetExpressions=true, datasetSchema=true  │
│     → Scan ID                                            │
├─────────────────────────────────────────────────────────┤
│  3. GET /admin/workspaces/scanStatus/{scanId}            │
│     → Poll until status = "Succeeded"                    │
├─────────────────────────────────────────────────────────┤
│  4. GET /admin/workspaces/scanResult/{scanId}            │
│     → Full workspace data including datasets, tables,    │
│       expressions, storageMode, contentProviderType      │
├─────────────────────────────────────────────────────────┤
│  5. GET /v1/workspaces/{wsId}/items/{itemId}             │
│     (Fabric Items API - resolves source type/name)       │
└─────────────────────────────────────────────────────────┘
```

## Key Technical Details

- **Scanner API batch limit:** 100 workspace IDs per `getInfo` call
- **contentProviderType values:** `InImportMode`, `PbixInImportMode`, `InCompositeMode`, `PbixInCompositeMode`, `PbixInDirectQueryMode`, `InDirectLakeMode`
- **Table storageMode values:** `Import`, `DirectQuery`, `DirectLake`, `Dual`
- **GUID detection:** When `Sql.Database()` uses a GUID as the database parameter, the Items API is called to resolve the actual name and type
- Both Lakehouse SQL Endpoints and Warehouses use `.datawarehouse.fabric.microsoft.com` — only the Items API can reliably distinguish them

## Requirements

- Microsoft Fabric workspace with a Spark-enabled notebook
- Python packages: `requests` (pre-installed in Fabric)
- Network access to `api.powerbi.com` and `api.fabric.microsoft.com`

## License

MIT
