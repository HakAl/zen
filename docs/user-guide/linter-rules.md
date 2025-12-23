# Zen Lint: Complete Rule Reference

Zen Lint is a universal "lazy coder detector" that scans for forbidden patterns. It runs automatically after every implementation step and can also be used standalone.

## Severity Levels

| Level | Behavior | Exit Code |
|-------|----------|-----------|
| **HIGH** | Blocks step completion | 1 |
| **MEDIUM** | Reported, does not block | 0 |
| **LOW** | Reported, does not block | 0 |

---

## HIGH Severity Rules

These rules indicate critical issues that will block the agent from proceeding.

### `API_KEY`
**Pattern:** Detects hardcoded API keys and secrets in code.
```python
# Triggers
api_key = "sk-1234567890abcdef"
config = {"secret": "my-secret-value-here"}

# OK (use environment variables)
api_key = os.getenv("API_KEY")
```

### `PLACEHOLDER`
**Pattern:** `[A-Z_]{2,}_HERE` — Unfilled placeholder values.
```python
# Triggers
DATABASE_URL_HERE
YOUR_API_KEY_HERE

# OK
DATABASE_URL = "postgresql://..."
```

### `POSSIBLE_SECRET`
**Pattern:** Inline password/secret assignments with literal values.
```python
# Triggers
password = "hunter2"
api_key = "sk-live-xxxxx"

# OK
password = os.getenv("DB_PASSWORD")
```

### `CONFLICT_MARKER`
**Pattern:** `^[<>=]{7}` — Git merge conflict markers.
```python
# Triggers
<<<<<<< HEAD
=======
>>>>>>> feature-branch
```

### `TRUNCATION_MARKER`
**Pattern:** AI-generated truncation indicators.
```python
# Triggers
... rest of implementation
... remaining code here
... etc

# OK (legitimate use)
items = [1, 2, 3, ...]  # Python ellipsis
```

### `INCOMPLETE_IMPL`
**Pattern:** TODO/FIXME with implementation keywords.
```python
# Triggers
# TODO: implement this function
# FIXME: finish error handling

# OK (descriptive, not action items)
# TODO: Consider caching for performance
```

### `OVERLY_GENERIC_EXCEPT`
**Pattern:** Bare `except:` without exception type.
```python
# Triggers
try:
    risky()
except:
    pass

# OK
except Exception as e:
    logger.error(e)
```

### `BARE_RETURN_IN_CATCH`
**Pattern:** JavaScript/TypeScript catch blocks that silently return.
```javascript
// Triggers
try { fetch() } catch (e) { return; }

// OK
catch (e) { console.error(e); return null; }
```

---

## MEDIUM Severity Rules

These indicate technical debt that should be addressed but won't block execution.

### `TODO` / `FIXME` / `HACK` / `XXX`
**Pattern:** Common comment markers for incomplete work.
```python
# Triggers
# TODO: add validation
# FIXME: this is broken
# HACK: workaround for bug
# XXX: refactor later
```

### `STUB_IMPL`
**Pattern:** Empty function bodies (`pass` or `...`).
```python
# Triggers
def process():
    pass

def handle():
    ...

# OK (abstract methods)
@abstractmethod
def process(self):
    pass
```

### `NOT_IMPLEMENTED`
**Pattern:** NotImplementedError or "not implemented" strings.
```python
# Triggers
raise NotImplementedError()
raise NotImplementedError("TODO")
return "not implemented"
```

### `HARDCODED_IP`
**Pattern:** Public IP addresses in code.
```python
# Triggers
server = "8.8.8.8"
endpoint = "203.0.113.1"

# OK (private/special IPs are allowed)
localhost = "127.0.0.1"
internal = "192.168.1.1"
docker = "172.17.0.1"
```

### `AI_COMMENT_BOILERPLATE`
**Pattern:** Verbose AI-generated comments.
```python
# Triggers
# This function is used to process data
# The following method is responsible for validation

# OK (concise)
# Process incoming data
```

### `INLINE_IMPORT`
**Pattern:** Imports inside functions (not at top of file).
```python
# Triggers
def process():
    import json  # Should be at top
    from utils import helper

# OK
import json

def process():
    return json.dumps(data)
```

---

## LOW Severity Rules

Code smells and cleanup opportunities.

### `DEBUG_PRINT`
**Pattern:** Debug output statements.
```python
# Triggers
print(debug_value)
console.log(data)
System.out.println(x)
fmt.Println(value)
```

### `DEAD_COMMENT`
**Pattern:** Comments indicating dead or unused code.
```python
# Triggers
# unused variable
# dead code below
# commented-out function
# remove this later
```

### `TEMP_FIX`
**Pattern:** Temporary workaround indicators.
```python
# Triggers
# temp fix for issue
# temporary workaround
# band-aid solution
```

### `LINT_DISABLE`
**Pattern:** Linter suppression comments.
```python
# Triggers
# noqa
# pylint: disable=all
# eslint-disable-next-line
# @ts-ignore
```

### `EXAMPLE_DATA`
**Pattern:** Placeholder/example values in code.
```python
# Triggers
email = "john.doe@example.com"
name = "foo"
company = "acme"
text = "lorem ipsum"
```

### `CATCH_ALL_EXCEPTION`
**Pattern:** Catching base Exception class.
```python
# Triggers
except Exception as e:
catch (Exception e)
catch (Throwable t)

# OK (specific exceptions)
except ValueError as e:
except (IOError, OSError) as e:
```

### `MAGIC_NUMBER`
**Pattern:** Time-related magic numbers.
```python
# Triggers
timeout = 86400   # seconds in a day
cache_ttl = 3600  # seconds in an hour

# OK (use named constants)
SECONDS_PER_DAY = 86400
timeout = SECONDS_PER_DAY
```

### `EMPTY_CATCH`
**Pattern:** Exception handling that does nothing.
```python
# Triggers
except ValueError:
    pass

try { } catch (e) { }
```

### `COPY_PASTE_COMMENT`
**Pattern:** Comments indicating copied code.
```python
# Triggers
# copied from stackoverflow
# copy-pasted from utils.py
# stolen from legacy module
```

### `EMPTY_DOCSTRING`
**Pattern:** Docstrings with no content.
```python
# Triggers
def process():
    """"""
    return data

def handle():
    '''   '''
    pass
```

---

## Suppression

### Inline Suppression

Suppress a specific rule for one line:
```python
print(debug)  # lint:ignore DEBUG_PRINT
```

Suppress all rules for one line:
```python
password = "test123"  # lint:ignore
```

### Config File

Create `.lintrc.json` in your project root:
```json
{
  "disabled_rules": ["DEBUG_PRINT", "MAGIC_NUMBER", "EXAMPLE_DATA"]
}
```

---

## Test File Exemptions

The following rules are automatically skipped in test files (`test_*.py`, `*_test.py`, `*.spec.ts`, etc.):

- `API_KEY` — Mock credentials are common in tests
- `POSSIBLE_SECRET` — Test fixtures often contain fake secrets
- `EXAMPLE_DATA` — Test data naturally uses example values

---

## Output Formats

```bash
# Default text output
zen_lint.py

# JSON (for programmatic use)
zen_lint.py --format json

# SARIF (for GitHub Code Scanning)
zen_lint.py --format sarif
```

---

## Supported Languages

The linter understands comment syntax for:

| Extension | Line Comment | Block Comment |
|-----------|--------------|---------------|
| `.py`, `.pyi` | `#` | `"""..."""` |
| `.js`, `.ts`, `.jsx`, `.tsx` | `//` | `/*...*/` |
| `.java`, `.kt`, `.scala` | `//` | `/*...*/` |
| `.c`, `.cpp`, `.h`, `.hpp` | `//` | `/*...*/` |
| `.go`, `.rs`, `.swift` | `//` | `/*...*/` |
| `.rb` | `#` | `=begin...=end` |
| `.sh`, `.bash`, `.zsh` | `#` | — |
| `.sql` | `--` | `/*...*/` |
| `.lua` | `--` | `--[[...]]` |
| `.yaml`, `.yml`, `.toml` | `#` | — |
