# VCF Operations Metrics Explorer
## MVP Product and Technical Specification

**Status:** Proposed MVP  
**Source references:**
- https://github.com/sentania/sharableScripts/tree/main/vropsMetrics
- https://github.com/brockpeterson/miscellaneous/tree/main/vcf_operations_metric_picker

### 1. Product goal

Create an open-source, standalone, cross-platform VCF Operations metric discovery and extraction utility.

Users must be able to discover objects and metric definitions directly from a connected VCF Operations environment, assemble metric collection jobs, execute them, and export results without writing code or manually discovering API keys.

The same functional engine must be available through a GUI and a fully scriptable CLI.

### 2. Core requirements

**R1. Connection and authentication**
- Connect to a user-specified VCF Operations endpoint over HTTPS.
- Support username/password, optional authentication source, and existing OpsToken.
- Prompt interactively for passwords where appropriate.
- Support token input through environment variables or secure secret injection.
- Validate TLS certificates by default.
- Allow explicitly disabling TLS verification for lab environments with visible warnings.
- Never save passwords or tokens inside collection profiles.
- Show connection status and actionable authentication errors.

**R2. Dynamic inventory discovery**
- Retrieve supported resource kinds from the connected server where the API supports discovery.
- Initially prioritize `VirtualMachine`, `HostSystem`, `ClusterComputeResource`, and `Datastore`.
- Support paginated resource discovery.
- Allow object search by name, object type, and optionally additional API-supported properties.
- Support selecting one, many, or all matching objects.
- Support importing resource lists from CSV.
- Resolve imported names to persistent Operations resource IDs.
- Reject or explicitly flag ambiguous name matches.
- Preserve unresolved or missing entries in a validation report.

**R3. Metric discovery**
- Retrieve metric definitions available for the selected resource kind and adapter kind.
- Provide searchable metric names, raw stat keys, units, and descriptions.
- Allow selection of multiple metrics.
- Support manual raw stat key entry as a fallback.
- Support built-in starter metric sets.
- Distinguish a metric existing in a catalogue from its availability on an individual object.
- Show unsupported or unavailable metrics rather than silently dropping them.
- Avoid assuming all adapters of the same resource kind expose identical metrics.

**R4. Collection groups**
A collection job contains one or more independent groups.

Each group defines:
- A human-readable group name.
- A resource kind.
- A dynamic or explicit object selection.
- A set of metric stat keys.
- Optional query overrides where supported.

Support:
- All objects of a kind.
- Explicit object selections.
- Imported arbitrary object lists.
- Multiple groups with different metric selections.
- Overlapping membership without duplicate output ambiguity.
- A stable group identifier for reproducibility.

**R5. Historical metric retrieval**
- Support explicit start and end times.
- Support relative ranges such as last hour, last day, and last seven days.
- Support interval and rollup options exposed by the target API.
- Provide raw or unrolled results when the API supports them.
- Support bounded concurrent collection and batched resource queries.
- Prefer batching where efficient and supported.
- Fall back to smaller batches or per-object retrieval as required.
- Do not silently substitute latest-N-samples behavior for an explicit historical query.
- Handle independent metric timestamps correctly.
- Preserve missing data as null with associated status information.
- Support cancellation, retries, timeouts, and partial results.

**R6. Export**
MVP export formats:
- CSV for common analysis tools.
- JSON for structured ingestion.
- XLSX for Excel users.
- Terminal table for CLI users.

Every export must preserve:
- Group identity.
- Resource kind.
- Object name.
- Operations resource ID.
- Metric stat key.
- Timestamp in UTC.
- Metric value and unit.
- Collection metadata.

CSV and Excel should support both:
- Long format: one metric value per row.
- Wide format: one object/timestamp per row, with metrics as columns.

Long format is canonical. Wide format is derived through timestamp-based alignment.

The JSON format must preserve collection groups, resources, metrics, values, errors, and query metadata.

For Excel, handle worksheet row limits and protect against spreadsheet formula injection.

**R7. Reusable collection profiles**
- Save and load reusable profiles in versioned JSON or YAML.
- Profiles define selectors, metric groups, time range, and output settings.
- Profiles may contain a server address or alias, but never passwords or tokens.
- Support executing the same profile through GUI or CLI.
- Validate profiles before running.
- Include a schema version for future compatibility.

**R8. GUI**
Provide:
1. Connection screen.
2. Object and resource-type browser.
3. Live searchable metric picker.
4. Multiple collection group editor.
5. Time-range and collection settings.
6. Preflight summary of selected objects and metrics.
7. Collection progress, cancellation, and errors.
8. Results preview and exports.
9. Profile save/load.

The GUI must be usable without requiring the user to install Python, PowerShell, Node.js, or another language runtime.

A localhost browser GUI is acceptable for the MVP if the application starts it automatically and packages all required components.

The localhost service must be bound to loopback, protected against cross-origin requests, and shut down when the application exits.

**R9. CLI**
Provide script-friendly subcommands:

- `connect test`
- `objects kinds`
- `objects search`
- `metrics list`
- `profiles validate`
- `collect`
- `profiles run`

Support both individual command arguments and complete profile files.

CLI must support:
- Non-interactive authentication.
- Machine-readable stdout.
- Progress and diagnostics on stderr.
- Useful exit codes.
- Quiet mode.
- Deterministic output files.
- `--help` for all commands.

**R10. Cross-platform distribution**
Provide packaged executables for:
- Windows x64.
- macOS Apple Silicon and Intel, or a tested universal build.
- Linux x64, with ARM64 as an optional additional target.

Windows releases must be Authenticode signed.

macOS releases must be Developer ID signed, hardened-runtime compatible where applicable, and Apple notarized.

Linux releases must include an executable and documented checksums, with artifact signatures preferred.

Release processes must not expose signing keys, authentication tokens, or certificates.

Signing and notarization are required release acceptance gates, but local development builds may be unsigned and clearly identified.

### 3. Data model

**Connection**
- endpoint
- authentication configuration
- certificate verification preference

**ObjectSelector**
- resource kind
- adapter kind, where needed
- selection mode (`all`, `search`, `explicit`, `imported`)
- query/filter parameters
- resolved resource IDs

**MetricSet**
- metric stat keys
- associated catalogue metadata
- optional friendly display names

**CollectionGroup**
- stable group ID
- name
- object selector
- metric set
- optional query overrides

**CollectionJob**
- schema version
- connection reference
- one or more collection groups
- UTC time range
- rollup/interval settings
- export settings

**MetricSample**
- group ID
- resource ID
- resource kind
- metric key
- UTC timestamp in milliseconds
- value
- quality/status metadata when returned

**CollectionResult**
- request metadata
- resolved selections
- samples
- warnings
- per-object and per-metric errors
- completion/partial/cancelled status

### 4. Collection engine

Use a shared engine for both interfaces.

Pipeline:

1. Parse and validate the collection job.
2. Authenticate and inspect server capabilities.
3. Resolve resource selections using paginated inventory APIs.
4. Resolve metric definitions and availability.
5. Construct an execution plan.
6. Deduplicate identical object/metric/time requests where safe.
7. Partition API requests into bounded batches.
8. Execute with retries, throttling, and progress reporting.
9. Normalize timestamped metric series.
10. Export canonical results into requested formats.

Do not assume that all metrics share identical timestamps.

Avoid giant query strings that exceed practical URL or proxy limits. Prefer supported batch request forms and chunking. Confirm endpoint capabilities against the target product/version before implementation.

Retry transient failures with bounded exponential backoff and jitter, respecting Retry-After when available. Do not blindly retry authentication and validation failures.

### 5. Security and resilience

- Default to trusted TLS verification.
- Never write secrets to application logs, history, profiles, or exports.
- Redact authentication headers and credentials from errors.
- Restrict any local web interface to loopback.
- Protect local state-changing requests from cross-origin attacks.
- Avoid loading remote HTML or scripts into a privileged context.
- Limit request concurrency and memory usage.
- Apply output size and sample-count preflight estimates.
- Preserve partial results and clear failure summaries.
- Never hide collection errors behind an apparently complete export.

### 6. Performance expectations

The application must handle a representative environment containing thousands of inventory objects without requiring the complete inventory to be loaded into a single oversized API response.

Collection should use bounded memory where practical.

Measure:
- API call count.
- Collection elapsed time.
- Objects and metrics processed.
- Samples retrieved.
- Failed requests.
- Retry counts.

Compare batch and per-object retrieval using a repeatable test harness.

No unsupported performance targets or percentage improvement claims are required for the MVP.

### 7. Out of scope for MVP

- Metric dashboards and graph visualization beyond a basic preview.
- Scheduled background collection.
- Multi-server aggregation.
- Persistent metrics database.
- Alerting and anomaly detection.
- AI-based metric recommendations.
- Automatic metric correlation.
- Enterprise RBAC administration.
- Uploading exports to external cloud services.

Design extension points where useful but do not implement these features prematurely.

### 8. Acceptance criteria

**AC1: All hosts**
Given a working VCF Operations connection, select all `HostSystem` objects and metrics A/B/C. Collect a specified historical range, export CSV and XLSX, and verify the object coverage and returned timestamps.

**AC2: Three VMs**
Select three distinct VM resource IDs and metrics A/B/C. Verify that only those VMs are collected.

**AC3: Two VM groups**
Create group 1 with arbitrary VMs and metrics A/B/C. Create group 2 with arbitrary VMs and metrics D/E/F. Verify correct attribution, overlapping objects, and exports.

**AC4: Profile reproducibility**
Save a GUI-created profile and execute the same job through the CLI. Verify equivalent resolved selections, query parameters, and data, allowing only legitimate timing differences for relative ranges.

**AC5: Discovery**
Demonstrate server-side inventory pagination, object search, and metric catalogue lookup. Unsupported metrics must be indicated explicitly.

**AC6: Failure behavior**
Test invalid credentials, certificate errors, missing objects, duplicate names, unavailable stat keys, API throttling, incomplete results, and user cancellation.

**AC7: Data integrity**
Using mocked API responses with misaligned timestamps, verify correct null alignment and preservation of metric values.

**AC8: Distribution**
Validate GUI and CLI functionality on Windows, macOS, and Linux packaged builds. Verify Windows signature, macOS notarization, and Linux artifact integrity.

**AC9: Automation**
Execute a saved profile non-interactively with credentials supplied securely at runtime, producing a machine-readable export and meaningful process exit status.

### 9. Implementation approach

Prefer Python for the initial architecture because Brock's implementation provides an existing reference for the API client, GUI, export behavior, and concurrent retrieval.

Reuse proven logic where compatible, but separate the domain model, API client, collection engine, CLI, GUI, and exporters.

Assess PyInstaller or comparable packaging tools against the native-signing and notarization requirements before committing to distribution.

Avoid adding a large desktop framework unless necessary. Prefer a lightweight localhost web interface served by the packaged application.

### 10. Definition of done

The MVP is complete when all three user scenarios work through both GUI and CLI; results are accurate and reproducible; tests cover major API and data-integrity failure modes; and documented release artifacts exist for the three required platforms with the prescribed trust controls.

Do not claim AC8 is met merely because packaging configuration exists. The actual build/signing/notarization process must be executed and validated with appropriate credentials.
