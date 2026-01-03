#!/usr/bin/env python3
"""
Download Snapchat memories from the HTML export file.
Extracts URLs from the memories_history.html file and downloads them to a temp folder.
"""

import os
import re
import requests
import zipfile
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import piexif

# Thread-safe counter for progress tracking
download_lock = threading.Lock()

# Retry configuration
MAX_RETRIES = 5
INITIAL_BACKOFF = 1  # Initial backoff in seconds
MAX_BACKOFF = 60  # Maximum backoff in seconds


def extract_urls_from_html(html_file):
    """Extract download URLs and metadata from the HTML file."""
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Pattern to match the table rows with download links
    # Looking for: onclick="downloadMemories('URL', this, true)"
    pattern = r'<tr><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td><td>.*?downloadMemories\(\'(https://[^\']+)\''

    matches = re.findall(pattern, content, re.DOTALL)

    memories = []
    for match in matches:
        date_str, media_type, location, url = match
        memories.append({
            'date': date_str.strip(),
            'type': media_type.strip(),
            'location': location.strip(),
            'url': url
        })

    return memories


def sanitize_filename(filename):
    """Remove invalid characters from filename."""
    return re.sub(r'[<>:"/\\|?*]', '_', filename)


def download_with_retry(url, timeout=30):
    """Download a file with exponential backoff retry logic."""
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, stream=True, timeout=timeout)

            # Check for rate limiting or server errors
            if response.status_code == 429:  # Too Many Requests
                raise requests.exceptions.RequestException("Rate limited (429)")
            elif response.status_code >= 500:  # Server errors
                raise requests.exceptions.RequestException(f"Server error ({response.status_code})")

            response.raise_for_status()
            return response

        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            if attempt == MAX_RETRIES - 1:
                # Last attempt, raise the error
                raise

            # Calculate exponential backoff
            backoff = min(INITIAL_BACKOFF * (2 ** attempt), MAX_BACKOFF)

            with download_lock:
                print(f"    Retry {attempt + 1}/{MAX_RETRIES} after {backoff}s due to: {e}")

            time.sleep(backoff)

    raise requests.exceptions.RequestException("Max retries exceeded")

def add_metadata_to_file(file):
    # Add metadata (date, time etc.) to the downloaded file
    filename = file.stem  # Get filename without extension
    date_part = filename.split('_')[0]  # Get the date part
    time_part = filename.split('_')[1] if '_' in filename else '120000'  # Default time if not present

    if len(date_part) == 8 and date_part.isdigit():
        year = date_part[0:4]
        month = date_part[4:6]
        day = date_part[6:8]

        hour = time_part[0:2]
        minute = time_part[2:4]
        second = time_part[4:6]

        # Create a timestamp for the specified date and time
        spec_time = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second)).timestamp()
        # Prepare EXIF date format
        exif_date = f"{year}:{month}:{day} {hour}:{minute}:{second}"

        try:
            # Load existing exif or create new if empty
            exif_dict = piexif.load(str(file))
            
            exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal] = exif_date
            exif_dict['Exif'][piexif.ExifIFD.DateTimeDigitized] = exif_date
            
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, str(file))
        except Exception as e:
            print(f"Could not update EXIF for {file.name}: {e}")
        
        # Set the modified and accessed date and time of the file
        os.utime(file, times=(spec_time, spec_time))


def download_memory(memory, temp_folder, index, progress_info=None, failed_list=None):
    """Download a single memory file and extract from ZIP if needed."""
    url = memory['url']
    date_str = memory['date']
    media_type = memory['type']

    # Parse date to create filename prefix
    try:
        # Format: 2025-12-24 17:33:36 UTC
        dt = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S UTC')
        date_prefix = dt.strftime('%Y%m%d_%H%M%S')
    except:
        date_prefix = f"memory_{index:04d}"

    # Initialize temp_filepath with thread ID to avoid collisions
    import threading
    thread_id = threading.get_ident()
    temp_filepath = temp_folder / f"{date_prefix}_temp_{thread_id}"

    try:
        with download_lock:
            print(f"[{index}] Downloading {date_prefix}...")

        # Download the file with retry logic
        response = download_with_retry(url, timeout=30)

        # Save to temporary file
        with open(temp_filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # Check if it's a ZIP file
        is_zip = False
        try:
            with zipfile.ZipFile(temp_filepath, 'r') as zip_ref:
                is_zip = True
        except zipfile.BadZipFile:
            is_zip = False

        if is_zip:
            # Extract the ZIP contents
            with zipfile.ZipFile(temp_filepath, 'r') as zip_ref:
                # Get list of files in the zip
                zip_contents = zip_ref.namelist()

                # Extract each file with a proper name
                for zip_filename in zip_contents:
                    # Determine if it's the main file or overlay
                    if 'overlay' in zip_filename.lower():
                        suffix = '_overlay'
                    else:
                        suffix = ''

                    # Get the file extension from the zip content
                    _, ext = os.path.splitext(zip_filename)

                    # Create new filename
                    new_filename = f"{date_prefix}{suffix}{ext}"
                    new_filepath = temp_folder / sanitize_filename(new_filename)

                    # Handle duplicates
                    counter = 1
                    while new_filepath.exists():
                        new_filename = f"{date_prefix}{suffix}_{counter}{ext}"
                        new_filepath = temp_folder / sanitize_filename(new_filename)
                        counter += 1

                    # Extract and rename
                    with zip_ref.open(zip_filename) as source, open(new_filepath, 'wb') as target:
                        target.write(source.read())

                    with download_lock:
                        print(f"  [{index}] ✓ Extracted: {new_filename}")
        else:
            # It's a direct file (not a ZIP)
            # Determine extension based on media type
            extension = '.jpg' if media_type == 'Image' else '.mp4'

            # Create final filename
            final_filename = f"{date_prefix}{extension}"
            final_filepath = temp_folder / sanitize_filename(final_filename)

            # Handle duplicates
            counter = 1
            while final_filepath.exists():
                final_filename = f"{date_prefix}_{counter}{extension}"
                final_filepath = temp_folder / sanitize_filename(final_filename)
                counter += 1

            # Rename the temp file
            temp_filepath.rename(final_filepath)
            with download_lock:
                print(f"  [{index}] ✓ Saved: {final_filename}")

        # Remove the temporary file if it still exists
        if temp_filepath.exists():
            temp_filepath.unlink()

        if progress_info:
            with download_lock:
                progress_info['completed'] += 1
                print(f"\nProgress: {progress_info['completed']}/{progress_info['total']} completed\n")

        return True
    except Exception as e:
        error_msg = str(e)
        with download_lock:
            print(f"  [{index}] ✗ Failed: {error_msg}")
            if failed_list is not None:
                failed_list.append({
                    'index': index,
                    'date': date_str,
                    'type': media_type,
                    'location': memory['location'],
                    'url': url,
                    'error': error_msg
                })
        # Clean up temp file if it exists
        if temp_filepath.exists():
            temp_filepath.unlink()
        return False

def main():
    # Configuration
    MAX_WORKERS = 28  # Number of parallel downloads (targeting ~30 minutes for 25k memories)

    # Setup paths
    script_dir = Path(__file__).parent
    html_file = script_dir / 'memories_history.html'
    temp_folder = script_dir / 'temp'
    
    # On Linux, if you want to save directly to a USB drive 
    # usb_drive = Path('/media/USERNAME/NAME OF_USB')  # Change USERNAME and NAME OF USB accordingly
    # temp_folder = usb_drive / 'temp'

    # Create temp folder
    temp_folder.mkdir(exist_ok=True)
    print(f"Created temp folder: {temp_folder}")

    # Check if HTML file exists
    if not html_file.exists():
        print(f"Error: {html_file} not found!")
        return

    # Extract URLs
    print(f"\nExtracting URLs from {html_file.name}...")
    memories = extract_urls_from_html(html_file)
    print(f"Found {len(memories)} memories to download")
    print(f"Using {MAX_WORKERS} parallel workers\n")

    # Progress tracking
    progress_info = {'completed': 0, 'total': len(memories)}
    failed_downloads = []
    successful = 0
    failed = 0

    # Download memories in parallel
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all download tasks
        future_to_memory = {
            executor.submit(download_memory, memory, temp_folder, i, progress_info, failed_downloads): (i, memory)
            for i, memory in enumerate(memories, 1)
        }

        # Process completed downloads
        for future in as_completed(future_to_memory):
            i, memory = future_to_memory[future]
            try:
                if future.result():
                    successful += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"[{i}] Exception occurred: {e}")
                failed += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"Download complete!")
    print(f"  ✓ Successful: {successful}")
    print(f"  ✗ Failed: {failed}")
    print(f"  Total: {len(memories)}")
    print(f"Files saved to: {temp_folder}")
    print(f"{'='*60}")

    # Print failed downloads if any
    if failed_downloads:
        print(f"\n{'='*60}")
        print(f"FAILED DOWNLOADS ({len(failed_downloads)}):")
        print(f"{'='*60}\n")
        for fail in failed_downloads:
            print(f"[{fail['index']}] {fail['date']} - {fail['type']}")
            print(f"  Location: {fail['location']}")
            print(f"  Error: {fail['error']}")
            print(f"  URL: {fail['url']}")
            print()
    
    print("Now changing metadata of downloaded files...")
    # Using multiple workers to add metadata
    # Download memories in parallel
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for file in temp_folder.iterdir():
            if file.is_file():
                futures.append(executor.submit(add_metadata_to_file, file))
        
        # Wait for all to complete
        for future in as_completed(futures):
            pass
    
    print("Metadata update complete.")


if __name__ == '__main__':
    main()
