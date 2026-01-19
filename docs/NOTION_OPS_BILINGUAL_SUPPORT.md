# Notion Ops Agent - Bilingual Support Documentation

## Overview

The Notion Ops Agent has been enhanced with comprehensive bilingual support for Bosnian and English, along with advanced branch request capabilities for creating multiple related entities in a single operation.

## Features

### 1. Bilingual Property Mapping (Bosnian ↔ English)

The agent can now process requests in both Bosnian and English, automatically translating property names and values to the correct Notion database format.

#### Supported Property Mappings

| Bosnian | English | Notion Property |
|---------|---------|----------------|
| Cilj | Goal | Goal |
| Podcilj | Child Goal | Child Goal |
| Zadatak | Task | Task |
| Zadatak Status | Task Status | Status |
| Prioritet | Priority | Priority |
| Deadline / Rok | Due Date | Due Date |
| Napredak | Progress | Progress |
| Opis / Deskripcija | Description | Description |
| Agent / AI Agent | AI Agent | AI Agent |
| Veza s projektom | Project | Project |
| Veza s KPI | KPI | KPI |
| Veza s agentima | Agent Exchange DB | Agent Exchange DB |
| Početni datum | Start Date | Start Date |
| Završni datum | Target Deadline | Target Deadline |
| Povezani zadaci | Related Tasks | Related Tasks |
| Kategorija | Category | Category |
| Završeno | Is Completed | Is Completed? |
| Oznake / Tagovi | Tags | Tags |
| Komentari i bilješke | Agent Notes | Agent Notes |

#### Status Value Mappings

| Bosnian | English |
|---------|---------|
| Nije započet | Not started |
| U tijeku / U toku | In Progress |
| Završen | Completed |
| Blokiran | Blocked |
| Pauzirano | Paused |
| Otkazano | Cancelled |

#### Priority Value Mappings

| Bosnian | English |
|---------|---------|
| Nizak / Niska | Low |
| Srednji / Srednja | Medium |
| Visok / Visoka | High |
| Kritičan / Kritična | Critical |

### 2. Branch Request Support

Branch requests allow you to create multiple related entities (goals, child goals, tasks, projects, KPIs) in a single operation with automatic relationship linking.

#### Branch Request Syntax

**Bosnian:**
```
Grupni zadatak: Kreiraj 1 cilj + 5 taskova: <Title>
Grupni zahtjev: Napravi cilj sa 3 podciljeva i 10 zadataka: <Title>
```

**English:**
```
Branch request: Create 1 goal + 5 tasks: <Title>
Batch request: Create goal with 3 child goals and 10 tasks: <Title>
```

#### Supported Entity Types in Branch Requests

- **Goals (Ciljevi)**: Main parent goals
- **Child Goals (Podciljevi)**: Sub-goals linked to parent goals
- **Tasks (Zadaci)**: Tasks linked to goals and projects
- **Projects (Projekti)**: Projects linked to goals
- **KPIs**: Key Performance Indicators linked to goals/tasks

## Usage Examples

### Example 1: Simple Task Creation (Bosnian)

```
kreiraj zadatak sa sledećim podacima:
- naziv: Implementacija API-ja
- prioritet: visok
- rok: 2025-12-31
- opis: Potrebno implementirati REST API
- status: u tijeku
```

**Result**: Creates a task with:
- Name: "Implementacija API-ja"
- Priority: "High"
- Due Date: "2025-12-31"
- Description: "Potrebno implementirati REST API"
- Status: "In Progress"

### Example 2: Simple Task Creation (English)

```
create task with:
- title: API Implementation
- priority: high
- deadline: 2025-12-31
- description: Need to implement REST API
- status: in progress
```

**Result**: Same as above in English

### Example 3: Branch Request (Bosnian)

```
Grupni zadatak: Kreiraj 1 cilj + 5 taskova: Povećanje prihoda za Q1 2025

Prioritet: visok
Rok: 2025-03-31
```

**Result**: Creates:
- 1 Goal: "Povećanje prihoda za Q1 2025" (Priority: High, Due Date: 2025-03-31)
- 5 Tasks linked to the goal:
  - Task 1: "Task 1: Povećanje prihoda za Q1 2025"
  - Task 2: "Task 2: Povećanje prihoda za Q1 2025"
  - Task 3: "Task 3: Povećanje prihoda za Q1 2025"
  - Task 4: "Task 4: Povećanje prihoda za Q1 2025"
  - Task 5: "Task 5: Povećanje prihoda za Q1 2025"

### Example 4: Complex Branch Request with Child Goals (English)

```
Branch request: Create 1 goal with 3 child goals and 10 tasks: Product Launch 2025

Priority: high
Status: in progress
Deadline: 2025-06-30
```

**Result**: Creates:
- 1 Parent Goal: "Product Launch 2025"
- 3 Child Goals linked to parent:
  - "Product Launch 2025 - Podcilj 1"
  - "Product Launch 2025 - Podcilj 2"
  - "Product Launch 2025 - Podcilj 3"
- 10 Tasks linked to the parent goal

### Example 5: Project with Related Goals and Tasks (Bosnian)

```
Grupni zahtjev: Kreiraj 1 projekt sa 1 ciljem i 5 taskova: Digitalna transformacija

Prioritet: visok
Kategorija: IT
```

**Result**: Creates:
- 1 Project: "Digitalna transformacija"
- 1 Goal linked to the project: "Digitalna transformacija"
- 5 Tasks linked to both the goal and project

## Technical Implementation

### Architecture

```
User Input (Bosnian/English)
    ↓
NotionKeywordMapper (Translation)
    ↓
BranchRequestHandler (Parsing)
    ↓
NotionSchemaRegistry (Validation)
    ↓
NotionOpsAgent (Proposal)
    ↓
Approval Pipeline
    ↓
NotionService (Execution)
    ↓
Notion API
```

### Key Components

#### 1. NotionKeywordMapper

**Location**: `services/notion_keyword_mapper.py`

**Purpose**: Translates Bosnian property names and values to English equivalents.

**Key Methods**:
- `translate_property_name(property_name: str) -> str`: Translates a single property name
- `translate_status_value(status: str) -> str`: Translates status values
- `translate_priority_value(priority: str) -> str`: Translates priority values
- `translate_payload(payload: Dict) -> Dict`: Translates entire payload
- `detect_intent(text: str) -> Optional[str]`: Detects user intent from text
- `is_batch_request(text: str) -> bool`: Checks if text is a branch request

#### 2. BranchRequestHandler

**Location**: `services/branch_request_handler.py`

**Purpose**: Parses and processes branch requests for creating multiple related entities.

**Key Methods**:
- `parse_branch_request(prompt: str) -> Optional[Dict]`: Parses a branch request
- `build_branch_operations(branch_request: Dict) -> List[Dict]`: Builds operations list
- `process_branch_request(prompt: str) -> Optional[Dict]`: End-to-end processing

#### 3. NotionSchemaRegistry (Enhanced)

**Location**: `services/notion_schema_registry.py`

**New Methods**:
- `translate_properties_payload(payload: Dict, db_key: str) -> Dict`: Translates properties for a specific database
- `normalize_create_payload(payload: Dict, db_key: str) -> Dict`: Normalizes and validates payload

### Integration Points

#### Agent Configuration

The Notion Ops agent keywords have been updated in `config/agents.json`:

```json
{
  "id": "notion_ops",
  "keywords": [
    "notion", "database", "page", "create", "delete", "update",
    "kreiraj", "napravi", "ažuriraj", "azuriraj", "baza",
    "cilj", "zadatak", "projekt", "grupni", "batch", "branch"
  ]
}
```

#### Notion Ops Agent

The agent now includes bilingual support in its trace metadata:

```python
{
  "agent": "notion_ops",
  "bilingual_support": True,
  "supported_languages": ["bosnian", "english"]
}
```

## Testing

### Test Coverage

**Keyword Mapper Tests**: 23 tests
- Property name translation
- Status/priority value translation
- Payload translation
- Intent detection
- Batch request detection

**Branch Request Handler Tests**: 27 tests
- Branch request parsing
- Entity count extraction
- Property extraction
- Operation building
- End-to-end processing
- Edge cases

### Running Tests

```bash
# Run keyword mapper tests
python -m pytest tests/test_notion_keyword_mapper.py -v

# Run branch request handler tests
python -m pytest tests/test_branch_request_handler.py -v

# Run all tests
python -m pytest tests/test_notion_keyword_mapper.py tests/test_branch_request_handler.py -v
```

## API Reference

### Creating a Single Task (Bilingual)

**Bosnian Request**:
```json
{
  "message": "kreiraj zadatak: Test Task",
  "metadata": {
    "zadatak": "Test Task",
    "prioritet": "visok",
    "rok": "2025-12-31",
    "status": "u tijeku"
  }
}
```

**English Request**:
```json
{
  "message": "create task: Test Task",
  "metadata": {
    "task": "Test Task",
    "priority": "high",
    "deadline": "2025-12-31",
    "status": "in progress"
  }
}
```

### Creating a Branch Request

**Request**:
```json
{
  "message": "Grupni zadatak: Kreiraj 1 cilj + 5 taskova: Revenue Growth",
  "metadata": {
    "prioritet": "visok",
    "rok": "2025-12-31"
  }
}
```

**Response** (proposal):
```json
{
  "text": "Notion Ops: returning command proposal for approval. Supporting Bosnian and English.",
  "proposed_commands": [{
    "command": "ceo.command.propose",
    "args": {
      "prompt": "...",
      "type": "branch_request",
      "supports_bilingual": true
    },
    "requires_approval": true,
    "risk": "HIGH"
  }],
  "trace": {
    "bilingual_support": true,
    "supported_languages": ["bosnian", "english"]
  }
}
```

## Best Practices

### 1. Use Clear Language

Always use clear, unambiguous language in either Bosnian or English. The system will automatically detect and translate.

### 2. Specify All Required Fields

For best results, include all required fields in your request:
- Title/Name
- Priority (optional but recommended)
- Deadline (optional but recommended)
- Status (optional, defaults to "Not started")

### 3. Branch Requests Format

When creating branch requests, use the format:
```
Grupni zadatak: Kreiraj <count> <entity> + <count> <entity>: <Title>
```

### 4. Quoted Titles

For titles with special characters or complex formatting, use quotes:
```
Grupni zadatak: Kreiraj cilj: "Revenue Growth Q1'2025 - Strategic Initiative"
```

### 5. Properties After Title

Specify additional properties after the main request:
```
Grupni zadatak: Kreiraj 1 cilj + 5 taskova: Test

Prioritet: visok
Rok: 2025-12-31
Status: u tijeku
```

## Troubleshooting

### Issue: Properties not being translated

**Solution**: Ensure property names match the documented mappings. Property names are case-insensitive.

### Issue: Branch request not detected

**Solution**: Use the correct syntax with explicit counts and entity types:
```
Grupni zadatak: Kreiraj 1 cilj + 5 taskova: <Title>
```

### Issue: Relations not linking

**Solution**: Branch requests automatically link entities. Ensure you're using branch request syntax.

### Issue: Mixed language not working

**Solution**: While the system supports both languages, try to keep property names consistent within a single request.

## Migration Guide

### From English-Only to Bilingual

Existing English requests will continue to work without changes. To add Bosnian support:

1. **Update property names** using the mapping table above
2. **Translate status values** using the status mapping table
3. **Translate priority values** using the priority mapping table
4. **No code changes required** - translation happens automatically

### Example Migration

**Before (English only)**:
```python
{
  "title": "My Task",
  "priority": "high",
  "status": "in progress"
}
```

**After (Bosnian)**:
```python
{
  "zadatak": "Moj zadatak",
  "prioritet": "visok",
  "status": "u tijeku"
}
```

Both formats work and produce the same result!

## Future Enhancements

Potential future enhancements:
- Support for additional languages (Serbian Cyrillic, Croatian)
- More complex branch request patterns
- Automatic entity naming based on context
- Bulk updates in addition to bulk creates
- Template-based branch requests

## Support

For issues or questions:
1. Check the troubleshooting section
2. Review the examples
3. Run the test suite to verify functionality
4. Check the implementation in `services/notion_keyword_mapper.py` and `services/branch_request_handler.py`
