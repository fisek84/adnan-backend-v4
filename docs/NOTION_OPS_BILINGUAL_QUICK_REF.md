# Notion Ops Agent - Quick Reference

## Property Mappings

### Core Properties

| Bosnian | English | Notion |
|---------|---------|--------|
| Cilj | Goal | Goal |
| Zadatak | Task | Task |
| Projekt | Project | Project |
| Naziv | Name | Name |
| Opis | Description | Description |

### Status & Progress

| Bosnian | English | Notion |
|---------|---------|--------|
| Status | Status | Status |
| Prioritet | Priority | Priority |
| Napredak | Progress | Progress |
| Završeno | Is Completed | Is Completed? |

### Dates

| Bosnian | English | Notion |
|---------|---------|--------|
| Rok / Deadline | Due Date | Due Date |
| Početni datum | Start Date | Start Date |
| Završni datum | Target Deadline | Target Deadline |

### Relations

| Bosnian | English | Notion |
|---------|---------|--------|
| Podcilj | Child Goal | Child Goal |
| Veza s projektom | Project | Project |
| Veza s KPI | KPI | KPI |
| Povezani zadaci | Related Tasks | Related Tasks |

## Status Values

| Bosnian | English |
|---------|---------|
| Nije započet | Not started |
| U tijeku | In Progress |
| Završen | Completed |
| Blokiran | Blocked |

## Priority Values

| Bosnian | English |
|---------|---------|
| Nizak | Low |
| Srednji | Medium |
| Visok | High |

## Quick Examples

### Create Task (Bosnian)
```
kreiraj zadatak: Test Task
prioritet: visok
rok: 2025-12-31
```

### Create Task (English)
```
create task: Test Task
priority: high
deadline: 2025-12-31
```

### Branch Request (Bosnian)
```
Grupni zadatak: Kreiraj 1 cilj + 5 taskova: Revenue Growth
```

### Branch Request (English)
```
Branch request: Create 1 goal + 5 tasks: Revenue Growth
```

## Syntax Patterns

### Single Entity
```
kreiraj <entity>: <title>
napravi <entity>: <title>
create <entity>: <title>
```

### Branch Request
```
Grupni zadatak: Kreiraj <N> <entity> + <M> <entity>: <title>
Branch request: Create <N> <entity> + <M> <entity>: <title>
```

### With Properties
```
<request>
<property>: <value>
<property>: <value>
```

## Supported Entities

- **Goal** (Cilj)
- **Child Goal** (Podcilj)
- **Task** (Zadatak)
- **Project** (Projekt)
- **KPI**

## Common Patterns

### 1. Goal + Tasks
```
Grupni zadatak: Kreiraj 1 cilj + 5 taskova: <Title>
```

### 2. Goal + Child Goals + Tasks
```
Kreiraj 1 cilj sa 3 podciljeva i 10 zadataka: <Title>
```

### 3. Project + Goal + Tasks
```
Kreiraj 1 projekt sa 1 ciljem i 5 taskova: <Title>
```

## Tips

✅ **Use quotes** for complex titles: `"My Title: Special Characters"`

✅ **Specify properties** after the main request

✅ **Mix languages** is supported but keep consistent per request

✅ **Case insensitive** - works with any casing

❌ **Don't mix formats** - choose either branch or single entity

❌ **Don't skip required fields** - at minimum provide a title
