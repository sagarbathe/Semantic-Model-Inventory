# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "4c04777f-4421-494b-a487-6267f904110a",
# META       "default_lakehouse_name": "lh_lineage_tracker",
# META       "default_lakehouse_workspace_id": "71e720ad-b206-414c-bfea-77ce0bf13024",
# META       "known_lakehouses": [
# META         {
# META           "id": "4c04777f-4421-494b-a487-6267f904110a"
# META         }
# META       ]
# META     }
# META   }
# META }

# MARKDOWN ********************

# # Semantic Model Inventory - Tenant-Wide Analysis
# # ================================================
# # This notebook scans all semantic models across the Fabric tenant and classifies them by storage mode:
# #   - Direct Lake on OneLake (expression points to ABFSS/OneLake path)
# #   - Direct Lake on SQL (expression points to a SQL endpoint)
# #   - Import (data is imported/cached in the model)
# #   - DirectQuery (live connection to source)
# #   - Composite (mixed Import + DirectQuery)
# #
# # ---- AUTHENTICATION OPTIONS ----
# # Option 1: Run as CURRENT USER (interactive, uses notebook identity)
# # Option 2: Run as SERVICE PRINCIPAL (SPN) using client credentials
# #
# # ---- REQUIRED PERMISSIONS ----
# # 
# # OPTION 1 - Run as User:
# #   - The user must be a Fabric Administrator OR have Power BI Service Admin role
# #     (Microsoft 365 Admin Center > Roles > Power BI Administrator)
# #   - Alternatively, the tenant setting "Admin API settings > Allow service principals 
# #     to use read-only admin APIs" must be DISABLED (so user-based admin calls work)
# #   - The user must have signed in with an account that has admin privileges
# #
# # OPTION 2 - Run as Service Principal (SPN):
# #   1. Register an App in Microsoft Entra ID (Azure AD)
# #   2. Create a Client Secret or Certificate for the app
# #   3. Create a Security Group in Entra ID and add the SPN to it
# #   4. In Power BI Admin Portal > Tenant Settings:
# #      a. "Allow service principals to use Power BI APIs" -> Enable for the security group
# #      b. "Allow service principals to use read-only admin APIs" -> Enable for the security group
# #      c. "Enhance admin APIs responses with detailed metadata" -> Enable
# #      d. "Enhance admin APIs responses with DAX and mashup expressions" -> Enable
# #   5. The SPN does NOT need workspace-level permissions (admin APIs are tenant-scoped)
# #   6. Store client_id, client_secret, and tenant_id in Azure Key Vault (recommended)
# #      OR pass them via notebook parameters
# #
# # ---- TENANT SETTINGS (both options) ----
# #   - "Enhance admin APIs responses with detailed metadata" -> Enabled
# #   - "Enhance admin APIs responses with DAX and mashup expressions" -> Enabled
# #     (Required to see dataset expressions which reveal Direct Lake source paths)


# CELL ********************

# CONFIGURATION - Choose authentication mode
# Set auth_mode = "user" or "spn"

auth_mode = "user"  # Change to "spn" for service principal authentication

# --- SPN Configuration (only needed if auth_mode = "spn") ---
# Option A: Retrieve from Key Vault (recommended)
# key_vault_url = "https://your-keyvault.vault.azure.net/"
# client_id_secret_name = "spn-client-id"
# client_secret_secret_name = "spn-client-secret"
# tenant_id_secret_name = "spn-tenant-id"

# Option B: Direct values (for testing only - do NOT hardcode in production)
spn_config = {
    "tenant_id": "<your-tenant-id>",
    "client_id": "<your-client-id>",
    "client_secret": "<your-client-secret>"
}

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

import requests
import json
import time
from datetime import datetime

def get_token_as_user():
    """Get Power BI access token using current notebook user identity."""
    token = notebookutils.credentials.getToken("https://analysis.windows.net/powerbi/api")
    return token

def get_token_as_spn(tenant_id, client_id, client_secret):
    """Get Power BI access token using Service Principal client credentials."""
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://analysis.windows.net/powerbi/api/.default"
    }
    response = requests.post(url, data=payload)
    if response.status_code != 200:
        raise Exception(f"SPN token acquisition failed: {response.status_code} - {response.text}")
    return response.json()["access_token"]

# Acquire token based on chosen auth mode
if auth_mode == "user":
    print("Authenticating as current user...")
    access_token = get_token_as_user()
elif auth_mode == "spn":
    print("Authenticating as Service Principal...")
    # Option A: From Key Vault (uncomment below)
    # client_id = notebookutils.credentials.getSecret(key_vault_url, client_id_secret_name)
    # client_secret = notebookutils.credentials.getSecret(key_vault_url, client_secret_secret_name)
    # tenant_id = notebookutils.credentials.getSecret(key_vault_url, tenant_id_secret_name)
    # access_token = get_token_as_spn(tenant_id, client_id, client_secret)
    
    # Option B: From config dict
    access_token = get_token_as_spn(
        spn_config["tenant_id"],
        spn_config["client_id"],
        spn_config["client_secret"]
    )
else:
    raise ValueError("auth_mode must be 'user' or 'spn'")

headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json"
}
print(f"Token acquired successfully at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Step 1: Get all workspaces that have been modified (use scanner API)
# The Scanner API is the recommended approach for tenant-wide inventory

base_url = "https://api.powerbi.com/v1.0/myorg/admin"

# Get modified workspaces (returns all workspace IDs)
print("Fetching workspace list...")
modified_url = f"{base_url}/workspaces/modified"
response = requests.get(modified_url, headers=headers)

if response.status_code != 200:
    raise Exception(f"Failed to get modified workspaces: {response.status_code} - {response.text}")

workspace_ids = [ws["id"] for ws in response.json()]
print(f"Found {len(workspace_ids)} workspaces to scan")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Step 2: Scan workspaces in batches using the Scanner API
# The API accepts up to 100 workspace IDs per call
# NOTE: datasetSchema MUST be true when datasetExpressions is true

def initiate_scan(workspace_batch, headers):
    """Initiate a workspace scan with dataset expressions enabled."""
    scan_url = f"{base_url}/workspaces/getInfo"
    params = {
        "datasetExpressions": "true",
        "datasetSchema": "true",
        "getArtifactUsers": "false",
        "lineage": "false"
    }
    body = {"workspaces": workspace_batch}
    resp = requests.post(scan_url, headers=headers, params=params, json=body)
    if resp.status_code in (200, 202):
        return resp.json()["id"]
    else:
        raise Exception(f"Scan initiation failed: {resp.status_code} - {resp.text}")

def poll_scan_status(scan_id, headers, max_wait=300):
    """Poll scan status until completion."""
    status_url = f"{base_url}/workspaces/scanStatus/{scan_id}"
    start_time = time.time()
    while time.time() - start_time < max_wait:
        resp = requests.get(status_url, headers=headers)
        if resp.status_code == 200:
            status = resp.json().get("status")
            if status == "Succeeded":
                return True
            elif status in ("Failed", "NotFound"):
                raise Exception(f"Scan {scan_id} failed with status: {status}")
        time.sleep(5)
    raise Exception(f"Scan {scan_id} timed out after {max_wait}s")

def get_scan_result(scan_id, headers):
    """Retrieve scan results."""
    result_url = f"{base_url}/workspaces/scanResult/{scan_id}"
    resp = requests.get(result_url, headers=headers)
    if resp.status_code == 200:
        return resp.json()
    else:
        raise Exception(f"Failed to get scan result: {resp.status_code} - {resp.text}")

# Process workspaces in batches of 100
batch_size = 100
all_scan_results = []

for i in range(0, len(workspace_ids), batch_size):
    batch = workspace_ids[i:i + batch_size]
    batch_num = (i // batch_size) + 1
    total_batches = (len(workspace_ids) + batch_size - 1) // batch_size
    print(f"Scanning batch {batch_num}/{total_batches} ({len(batch)} workspaces)...")
    
    scan_id = initiate_scan(batch, headers)
    poll_scan_status(scan_id, headers)
    result = get_scan_result(scan_id, headers)
    all_scan_results.append(result)
    
    # Brief pause between batches to avoid throttling
    if i + batch_size < len(workspace_ids):
        time.sleep(2)

print(f"Scanning complete. Processing results...")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Step 3: Parse scan results and classify each semantic model's storage mode
import re

GUID_PATTERN = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', re.IGNORECASE)

def is_guid(value):
    return bool(GUID_PATTERN.match(value.strip())) if value else False

def parse_expression_sources(expressions):
    result = {"connection_type": "", "server": "", "database": "", "onelake_path": "", "workspace_guid": "", "item_guid": ""}
    
    for expr in expressions:
        expr_text = expr.get("expression", "")
        
        # Pattern 1: Sql.Database("server", "database")
        sql_match = re.search(r'Sql\.Database\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"', expr_text)
        if sql_match:
            server = sql_match.group(1)
            database = sql_match.group(2)
            result["server"] = server
            result["connection_type"] = "sql_endpoint"
            # If database is a GUID, store as item_guid for later API resolution
            if is_guid(database):
                result["item_guid"] = database
                result["database"] = ""
            else:
                result["database"] = database
            return result
        
        # Pattern 2: ABFSS path
        abfss_match = re.search(r'abfss://([a-f0-9\-]{36})@onelake\.dfs\.fabric\.microsoft\.com/([a-f0-9\-]{36})', expr_text)
        if abfss_match:
            result["connection_type"] = "onelake"
            result["workspace_guid"] = abfss_match.group(1)
            result["item_guid"] = abfss_match.group(2)
            path_match = re.search(r'(abfss://[^\s"\']+)', expr_text)
            if path_match:
                result["onelake_path"] = path_match.group(1)
            return result
        
        # Pattern 3: AzureStorage.DataLake with OneLake URL
        dl_match = re.search(r'AzureStorage\.DataLake\s*\(\s*"(https://onelake\.[^"]+)"', expr_text)
        if dl_match:
            url = dl_match.group(1)
            result["connection_type"] = "onelake"
            result["onelake_path"] = url
            guids = re.findall(r'([a-f0-9\-]{36})', url)
            if len(guids) >= 2:
                result["workspace_guid"] = guids[0]
                result["item_guid"] = guids[1]
            elif len(guids) == 1:
                result["workspace_guid"] = guids[0]
            return result
        
        # Pattern 4: DatabaseQuery
        if "DatabaseQuery" in expr_text:
            result["connection_type"] = "onelake"
            guids = re.findall(r'([a-f0-9\-]{36})', expr_text)
            if len(guids) >= 2:
                result["workspace_guid"] = guids[0]
                result["item_guid"] = guids[1]
            return result
    
    return result


def determine_directlake_source(dataset):
    expressions = dataset.get("expressions", [])
    source_info = parse_expression_sources(expressions)
    if source_info["connection_type"] == "sql_endpoint":
        return ("Direct Lake on SQL", source_info)
    elif source_info["connection_type"] == "onelake":
        return ("Direct Lake on OneLake", source_info)
    else:
        return ("Direct Lake (Source Unknown - enable expression scanning)", source_info)


def classify_storage_mode(dataset):
    content_provider_type = dataset.get("contentProviderType", "")
    tables = dataset.get("tables", [])
    table_modes = set(t.get("storageMode", "") for t in tables if t.get("storageMode"))
    empty_source = {"connection_type": "", "server": "", "database": "", "onelake_path": "", "workspace_guid": "", "item_guid": ""}
    
    if "DirectLake" in table_modes:
        return determine_directlake_source(dataset)
    if content_provider_type:
        cpt_lower = content_provider_type.lower()
        if "directlake" in cpt_lower:
            return determine_directlake_source(dataset)
        elif "import" in cpt_lower:
            if "DirectQuery" in table_modes:
                return ("Composite (Import + DirectQuery)", empty_source)
            return ("Import", empty_source)
        elif "directquery" in cpt_lower:
            if "Import" in table_modes:
                return ("Composite (Import + DirectQuery)", empty_source)
            return ("DirectQuery", empty_source)
    if table_modes:
        if table_modes == {"Import"}:
            return ("Import", empty_source)
        elif table_modes == {"DirectQuery"}:
            return ("DirectQuery", empty_source)
        elif "Import" in table_modes and "DirectQuery" in table_modes:
            return ("Composite (Import + DirectQuery)", empty_source)
        elif "Dual" in table_modes:
            return ("Composite (Import + DirectQuery)" if "DirectQuery" in table_modes else "Import", empty_source)
        else:
            return (f"Mixed ({', '.join(sorted(table_modes))})", empty_source)
    if content_provider_type:
        return (content_provider_type, empty_source)
    return ("Unknown", empty_source)


# Parse all results
inventory_rows = []

for scan_result in all_scan_results:
    workspaces = scan_result.get("workspaces", [])
    for ws in workspaces:
        ws_name = ws.get("name", "")
        ws_id = ws.get("id", "")
        datasets = ws.get("datasets", [])
        for ds in datasets:
            ds_name = ds.get("name", "")
            ds_id = ds.get("id", "")
            configured_by = ds.get("configuredBy", "")
            content_provider_type = ds.get("contentProviderType", "")
            raw_table_modes = list(set(t.get("storageMode", "") for t in ds.get("tables", []) if t.get("storageMode")))
            
            storage_mode, source_info = classify_storage_mode(ds)
            
            inventory_rows.append({
                "workspace_name": ws_name,
                "workspace_id": ws_id,
                "semantic_model_name": ds_name,
                "semantic_model_id": ds_id,
                "storage_mode": storage_mode,
                "content_provider_type": content_provider_type,
                "table_storage_modes": ", ".join(sorted(raw_table_modes)),
                "source_type": "",
                "source_item_name": source_info.get("database", ""),
                "source_item_id": source_info.get("item_guid", ""),
                "source_workspace_id": source_info.get("workspace_guid", "") or ws_id,
                "sql_endpoint_server": source_info.get("server", ""),
                "onelake_path": source_info.get("onelake_path", ""),
                "configured_by": configured_by
            })

print(f"Classified {len(inventory_rows)} semantic models across {len(workspace_ids)} workspaces")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Step 4: Resolve source item details via Fabric Items API
# Uses GET /v1/workspaces/{wsId}/items/{itemId} to get displayName and type
# This correctly identifies Lakehouse vs Warehouse regardless of URL pattern

def resolve_source_items(rows, headers):
    fabric_base = "https://api.fabric.microsoft.com/v1"
    
    try:
        fabric_token = notebookutils.credentials.getToken("https://api.fabric.microsoft.com")
        fabric_headers = {"Authorization": f"Bearer {fabric_token}", "Content-Type": "application/json"}
    except:
        fabric_headers = headers
    
    # Collect unique (workspace_id, item_guid) pairs to resolve
    items_to_resolve = {}
    
    for row in rows:
        if "Direct Lake" not in row.get("storage_mode", ""):
            continue
        item_id = row.get("source_item_id", "")
        ws_id = row.get("source_workspace_id", "")
        if item_id and ws_id:
            key = (ws_id, item_id)
            if key not in items_to_resolve:
                items_to_resolve[key] = None
    
    if not items_to_resolve:
        print("No items to resolve.")
        return
    
    print(f"Resolving {len(items_to_resolve)} source items via Fabric Items API...")
    
    resolved_count = 0
    for (ws_id, item_guid) in items_to_resolve:
        try:
            url = f"{fabric_base}/workspaces/{ws_id}/items/{item_guid}"
            resp = requests.get(url, headers=fabric_headers)
            if resp.status_code == 200:
                data = resp.json()
                items_to_resolve[(ws_id, item_guid)] = {
                    "displayName": data.get("displayName", ""),
                    "type": data.get("type", ""),
                    "id": data.get("id", item_guid)
                }
                resolved_count += 1
            else:
                items_to_resolve[(ws_id, item_guid)] = {"displayName": "", "type": f"(HTTP {resp.status_code})", "id": item_guid}
        except Exception as e:
            items_to_resolve[(ws_id, item_guid)] = {"displayName": "", "type": "(Error)", "id": item_guid}
        time.sleep(0.3)
    
    # For items where we have a name but no GUID, resolve by listing workspace items
    items_by_name = {}
    for row in rows:
        if "Direct Lake" not in row.get("storage_mode", ""):
            continue
        item_id = row.get("source_item_id", "")
        item_name = row.get("source_item_name", "")
        ws_id = row.get("source_workspace_id", "")
        if item_name and ws_id and not item_id:
            key = (ws_id, item_name)
            if key not in items_by_name:
                items_by_name[key] = None
    
    ws_items_cache = {}
    for (ws_id, item_name) in items_by_name:
        try:
            if ws_id not in ws_items_cache:
                all_items = []
                url = f"{fabric_base}/workspaces/{ws_id}/items"
                resp = requests.get(url, headers=fabric_headers)
                if resp.status_code == 200:
                    all_items = resp.json().get("value", [])
                ws_items_cache[ws_id] = all_items
                time.sleep(0.3)
            
            matched = next((i for i in ws_items_cache[ws_id] if i.get("displayName", "").lower() == item_name.lower()), None)
            if matched:
                items_by_name[(ws_id, item_name)] = {
                    "displayName": matched["displayName"],
                    "type": matched.get("type", ""),
                    "id": matched.get("id", "")
                }
                resolved_count += 1
            else:
                items_by_name[(ws_id, item_name)] = {"displayName": item_name, "type": "", "id": ""}
        except:
            items_by_name[(ws_id, item_name)] = {"displayName": item_name, "type": "", "id": ""}
    
    # Apply resolved data to rows
    for row in rows:
        if "Direct Lake" not in row.get("storage_mode", ""):
            continue
        
        item_id = row.get("source_item_id", "")
        item_name = row.get("source_item_name", "")
        ws_id = row.get("source_workspace_id", "")
        
        resolved = None
        if item_id and ws_id and (ws_id, item_id) in items_to_resolve:
            resolved = items_to_resolve[(ws_id, item_id)]
        elif item_name and ws_id and (ws_id, item_name) in items_by_name:
            resolved = items_by_name[(ws_id, item_name)]
        
        if resolved:
            if resolved.get("displayName"):
                row["source_item_name"] = resolved["displayName"]
            if resolved.get("id"):
                row["source_item_id"] = resolved["id"]
            # Set source_type from the ACTUAL Fabric item type
            item_type = resolved.get("type", "")
            if item_type in ("Lakehouse", "Warehouse", "SQLEndpoint", "MirroredDatabase", "KQLDatabase"):
                row["source_type"] = item_type
            elif item_type:
                row["source_type"] = item_type
    
    print(f"Resolved {resolved_count}/{len(items_to_resolve) + len(items_by_name)} source items.")


resolve_source_items(inventory_rows, headers)
print("Enrichment complete.")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Step 5: Create DataFrame and display results

from pyspark.sql.types import StructType, StructField, StringType

schema = StructType([
    StructField("workspace_name", StringType(), True),
    StructField("workspace_id", StringType(), True),
    StructField("semantic_model_name", StringType(), True),
    StructField("semantic_model_id", StringType(), True),
    StructField("storage_mode", StringType(), True),
    StructField("content_provider_type", StringType(), True),
    StructField("table_storage_modes", StringType(), True),
    StructField("source_type", StringType(), True),
    StructField("source_item_name", StringType(), True),
    StructField("source_item_id", StringType(), True),
    StructField("source_workspace_id", StringType(), True),
    StructField("sql_endpoint_server", StringType(), True),
    StructField("onelake_path", StringType(), True),
    StructField("configured_by", StringType(), True)
])

if inventory_rows:
    df = spark.createDataFrame(inventory_rows, schema=schema)
    
    # Display summary counts by storage mode
    print("=" * 60)
    print("SEMANTIC MODEL STORAGE MODE SUMMARY")
    print("=" * 60)
    df.groupBy("storage_mode").count().orderBy("count", ascending=False).show(truncate=False)
    
    # Show breakdown by source type for Direct Lake
    print("=" * 60)
    print("DIRECT LAKE SOURCE BREAKDOWN")
    print("=" * 60)
    df.filter(df.storage_mode.contains("Direct Lake")) \
      .groupBy("storage_mode", "source_type").count() \
      .orderBy("count", ascending=False).show(truncate=False)
    
    print("=" * 60)
    print("DETAILED INVENTORY")
    print("=" * 60)
    df.select(
        "workspace_name", "semantic_model_name", "storage_mode",
        "source_type", "source_item_name", "source_item_id",
        "sql_endpoint_server", "configured_by"
    ).orderBy("storage_mode", "workspace_name", "semantic_model_name").show(200, truncate=False)
else:
    print("No semantic models found or insufficient permissions.")
    print("Ensure the required tenant settings are enabled (see Cell 1 for details).")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Step 6: (Optional) Save results to a lakehouse Delta table for historical tracking

# Uncomment below to persist results to a Delta table
df.write.mode("overwrite").format("delta").option("mergeSchema", "true").saveAsTable("semantic_model_inventory")
print("Results saved to table: semantic_model_inventory")



# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

display(df)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# # Show Direct Lake models with full source details:
# print("=" * 60)
# print("DIRECT LAKE MODELS - FULL SOURCE DETAILS")
# print("=" * 60)
# if inventory_rows:
#     df_direct_lake = df.filter(df.storage_mode.contains("Direct Lake"))
#     df_direct_lake.select(
#         "workspace_name", "semantic_model_name", "storage_mode",
#         "source_type", "source_item_name", "source_item_id",
#         "source_workspace_id", "sql_endpoint_server", "onelake_path"
#     ).show(200, truncate=False)
#     print(f"Total Direct Lake models: {df_direct_lake.count()}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
