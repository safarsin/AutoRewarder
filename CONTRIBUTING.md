# Contributing Localized Datasets

Thank you for your interest in helping improve AutoRewarder!

Currently, the tool uses a generic dataset [`queries.json`](https://github.com/safarsin/AutoRewarder/blob/main/assets/queries.json), but to make the automation look as natural as possible, we are collecting **Region & Language-specific search queries**. Having localized datasets helps reduce detection risks and improves the tool for everyone.

## How to Contribute

You can contribute in two ways: via GitHub Pull Request (if you know Git) or by simply submitting a text file.

### Option 1: For Developers (Pull Request)

If you know how to use Git, this is the preferred method. You'll automatically get a "Contributor" badge on GitHub.

1. **Fork** this repository.
2. Navigate to the `datasets` folder.
3. Find the JSON file for your region (e.g., `it-IT.json` for Italian, `en-AU.json` for Australian English). If your language file doesn't exist yet, you can create it!
4. Open the file and add natural search queries to the `queries` list.

`en-AU.json`:

```json
{
  "queries": [
    "what I need to do if I got beat up by a kangaroo",
    "woolworths online shopping",
    "can I sue a kangaroo for beating me up",
    "..."
  ]
}

```

5. Commit your changes and open a Pull Request.

### Option 2: For Users (Submit a File)

If you don't want to mess with JSON or Pull Requests, you can still help!

1. Create a simple `.txt` file with one search query per line.
2. Simply attach your `.txt` file to the comments of our **[Discussion](https://github.com/safarsin/AutoRewarder/discussions/59)**.
3. I'll format it into JSON, add it to the project, and manually add you to the contributors list.

Every query counts, even if you add just 100-500 new lines!

Thank you for making this project better!
