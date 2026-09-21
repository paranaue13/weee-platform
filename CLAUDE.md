# CLAUDE.md

## TOKEN-EFFICIENT WORKFLOW

Goal: Minimize token/context usage while preserving correctness and all existing functionality.

For every task:

### 1. SCOPE
- Work only on the module/tab/area explicitly mentioned by the user.
- Inspect only files directly required for that task.
- Do NOT scan or analyze the entire repository unless absolutely necessary.
- Do NOT inspect unrelated modules "just in case".
- Follow dependencies only when required for the requested change.

### 2. SCREENSHOTS
When the user provides a screenshot:
- Treat the screenshot as the primary UI reference.
- Focus only on the shown/marked UI area and the requested change.
- Locate only the source files responsible for that UI.
- Do NOT analyze other screens/modules unless required.
- A screenshot does not authorize a general UI review.

### 3. EXISTING FUNCTIONALITY
- Preserve all existing working functionality unless the user explicitly asks to change it.
- Do not refactor, redesign, rename, reorganize, or "improve" unrelated code.
- Make the smallest safe change that satisfies the request.

### 4. CONTEXT
- Do not reread files already inspected in the current task unless necessary.
- Do not read all documentation by default.
- Read only documentation relevant to the current module/task.
- Do not restate existing requirements or summarize the project unless asked.
- Prefer targeted search/file reads over broad repository exploration.

### 5. IMPLEMENTATION
- Once the requested change is clear, implement it directly.
- Do not spend tokens explaining the implementation before doing it.
- Do not create plans for simple/local changes.
- Do not provide long explanations after completion.
- Run only relevant checks/tests.
- Fix errors caused by the change, but do not investigate unrelated warnings/issues.

### 6. DEPENDENCIES
If completing the task requires another module/file:
- Inspect only the necessary dependency.
- Make the minimum required change.
- Do not expand the scope further.

### 7. AMBIGUITY
- Ask a question only when a missing detail could materially change the implementation.
- Do not ask for confirmation when the requested change is clear.
- Do not explore multiple alternatives unless requested.

### 8. RESPONSE
After completing a normal task, respond concisely with:
- Changed: `<short description>`
- Files: `<files changed>`
- Check: `<test/check result>`

Do not provide code excerpts, long summaries, or explanations unless requested.

### 9. USER PROMPT CONVENTION
The user may use:

```
TAB: <tab/module>
TASK: <requested change>
```

or simply provide a screenshot plus a short instruction.

Treat `TAB` as the hard scope boundary and `TASK` as the requested change.

If a screenshot clearly identifies the UI area, do not require the user to describe information already visible in the screenshot.

**Primary objective:** Use the minimum context, file reads, tool calls, output, and code changes necessary to complete each task safely.

## GIT CHECKPOINTS (υποχρεωτικό)

Το project έχει Git repository (`git init` έγινε στις 21/9/2026) ακριβώς για να μην χάνεται ποτέ ξανά δουλειά όπως συνέβη με το `desktop_v11.html` corruption incident. Κανόνες:

- **Πριν** από κάθε μεγάλη/ριψοκίνδυνη αλλαγή (π.χ. αναδιάρθρωση HTML/CSS, μαζικό edit, database migration, οτιδήποτε αγγίζει πολλά αρχεία ή δομή): τρέξε πρώτα
  ```
  git add -A && git commit -m "Πριν: <σύντομη περιγραφή τι πρόκειται να αλλάξει>"
  ```
  ώστε να υπάρχει πάντα ένα σημείο επιστροφής πριν ξεκινήσει η αλλαγή.
- **Μετά** από κάθε αλλαγή που επαληθεύτηκε ότι δουλεύει (π.χ. πέρασε το node --check / τα σχετικά tests / το Playwright verification): τρέξε
  ```
  git add -A && git commit -m "<σύντομη περιγραφή στα ελληνικά τι άλλαξε και δούλεψε>"
  ```
- Οι περιγραφές είναι σύντομες, στα ελληνικά, και λένε ΤΙ άλλαξε (όχι πώς ή γιατί με λεπτομέρειες).
- Δεν χρειάζεται checkpoint για ασήμαντες/διερευνητικές αλλαγές (π.χ. ένα debug script στο scratchpad) — μόνο για αλλαγές στον πραγματικό κώδικα της εφαρμογής (`backend/`, `android/`) που ο χρήστης θα κρατήσει.
- Το Git βρίσκεται στο `C:\Program Files\Git\bin\git.exe` — σε PowerShell που δεν το βλέπει ακόμα στο PATH, πρόσθεσε πρώτα: `$env:Path += ";C:\Program Files\Git\bin"`.
- `backend/.venv/`, `*.db`, `backend/.env`, `backend/uploads/` είναι σκόπιμα εκτός Git (.gitignore) — ποτέ μην τα προσθέσεις με `git add -f`.
