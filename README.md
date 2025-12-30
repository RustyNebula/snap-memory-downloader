# Snapchat Memories Downloader

A Python script to download all your Snapchat memories from the HTML export file provided by Snapchat's data download feature.

## What It Does

This tool extracts download URLs from Snapchat's `memories_history.html` file and downloads all your memories (photos and videos) in parallel. It handles:

- **Parallel downloads** with 28 concurrent workers for fast processing
- **Automatic retry logic** with exponential backoff for failed downloads
- **ZIP file extraction** for memories with overlays
- **Smart file naming** using timestamps from your memories
- **Duplicate handling** to prevent overwriting files
- **Progress tracking** to monitor download status

## Prerequisites

- Python 3.6 or higher
- `requests` library

## Installation

1. Clone this repository:
```bash
git clone https://github.com/RustyNebula/snap-memory-downloader.git
cd snap-memory-downloader
```

2. Install dependencies:
```bash
pip install requests
```

## Running Tests

The project includes comprehensive unit tests to verify functionality:

```bash
python3 test_download_memories.py
```

This will run 18 tests covering:
- HTML parsing and URL extraction
- Filename sanitization
- Download retry logic with exponential backoff
- File handling (images, videos, ZIP extraction)
- Duplicate filename handling
- Progress tracking
- Failed download tracking

## Getting Your Snapchat Data

Before using this tool, you need to request your data from Snapchat:

1. Open Snapchat and go to your profile
2. Tap the gear icon (Settings)
3. Scroll down to "My Data" under Account Actions
4. Tap "Submit Request"
5. Select what data you want (make sure "Memories" is selected)
6. Submit the request

Snapchat will email you when your data is ready (usually within 24 hours). Download the ZIP file and extract it. You'll need the `memories_history.html` file.

## Usage

1. Place the `memories_history.html` file in the same directory as `download_memories.py`

2. Run the script:
```bash
python3 download_memories.py
```

3. The script will:
   - Create a `temp` folder in the same directory
   - Extract all memory URLs from the HTML file
   - Download all memories in parallel
   - Display progress and summary statistics

## Output

- Downloaded files are saved to a `temp` folder
- Files are named with timestamps: `YYYYMMDD_HHMMSS.jpg` or `YYYYMMDD_HHMMSS.mp4`
- Memories with overlays will have both the original and overlay files saved

## Configuration

You can adjust these settings in the script:

- **MAX_WORKERS** (default: 28): Number of parallel downloads
- **MAX_RETRIES** (default: 5): Number of retry attempts for failed downloads
- **INITIAL_BACKOFF** (default: 1s): Starting delay for retries
- **MAX_BACKOFF** (default: 60s): Maximum delay between retries

## Features

- **Exponential Backoff**: Automatically retries failed downloads with increasing delays
- **Rate Limit Handling**: Detects and handles HTTP 429 (Too Many Requests) errors
- **ZIP Extraction**: Automatically extracts memories that come as ZIP files
- **Thread-Safe**: Uses locks to prevent race conditions during parallel downloads
- **Metadata Preservation**: Uses original timestamps for file naming

## Troubleshooting

**Script can't find `memories_history.html`**
- Make sure the file is in the same directory as the script
- Check that the filename matches exactly (case-sensitive)

**Downloads are failing**
- Check your internet connection
- The script will automatically retry up to 5 times
- If many downloads fail, try reducing MAX_WORKERS

**Out of disk space**
- The script downloads to a `temp` folder
- Make sure you have enough space for all your memories
- You can delete the `temp` folder and re-run if needed

## Notes

- The download URLs in the HTML file are temporary and may expire
- Download all your memories as soon as possible after receiving the data export
- Large collections may take significant time to download
- The script creates a `.gitignore` to prevent accidentally committing downloaded files

## License

MIT License - feel free to use and modify as needed.
