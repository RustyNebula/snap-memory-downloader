#!/usr/bin/env python3
"""
Unit tests for download_memories.py
"""

import unittest
from unittest.mock import Mock, patch, mock_open, MagicMock
import tempfile
import shutil
from pathlib import Path
import zipfile
import io
import requests

# Import the functions we want to test
from download_memories import (
    extract_urls_from_html,
    sanitize_filename,
    download_with_retry,
    download_memory
)


class TestExtractUrlsFromHtml(unittest.TestCase):
    """Test the extract_urls_from_html function."""

    def test_extract_single_memory(self):
        """Test extracting a single memory from HTML."""
        html_content = """
        <tr><td>2024-11-15 14:32:10 UTC</td><td>Image</td><td>San Francisco, CA</td><td><button onclick="downloadMemories('https://example.com/image.jpg', this, true)">Download</button></td></tr>
        """

        with patch('builtins.open', mock_open(read_data=html_content)):
            memories = extract_urls_from_html('test.html')

        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]['date'], '2024-11-15 14:32:10 UTC')
        self.assertEqual(memories[0]['type'], 'Image')
        self.assertEqual(memories[0]['location'], 'San Francisco, CA')
        self.assertEqual(memories[0]['url'], 'https://example.com/image.jpg')

    def test_extract_multiple_memories(self):
        """Test extracting multiple memories from HTML."""
        html_content = """
        <tr><td>2024-11-15 14:32:10 UTC</td><td>Image</td><td>San Francisco, CA</td><td><button onclick="downloadMemories('https://example.com/image.jpg', this, true)">Download</button></td></tr>
        <tr><td>2024-10-22 09:15:33 UTC</td><td>Video</td><td>New York, NY</td><td><button onclick="downloadMemories('https://example.com/video.mp4', this, true)">Download</button></td></tr>
        """

        with patch('builtins.open', mock_open(read_data=html_content)):
            memories = extract_urls_from_html('test.html')

        self.assertEqual(len(memories), 2)
        self.assertEqual(memories[0]['type'], 'Image')
        self.assertEqual(memories[1]['type'], 'Video')

    def test_extract_empty_html(self):
        """Test extracting from HTML with no memories."""
        html_content = "<html><body>No memories here</body></html>"

        with patch('builtins.open', mock_open(read_data=html_content)):
            memories = extract_urls_from_html('test.html')

        self.assertEqual(len(memories), 0)


class TestSanitizeFilename(unittest.TestCase):
    """Test the sanitize_filename function."""

    def test_sanitize_valid_filename(self):
        """Test that valid filenames are unchanged."""
        filename = "test_file_123.jpg"
        result = sanitize_filename(filename)
        self.assertEqual(result, filename)

    def test_sanitize_invalid_characters(self):
        """Test that invalid characters are replaced."""
        filename = 'test<>:"/\\|?*file.jpg'
        result = sanitize_filename(filename)
        self.assertEqual(result, 'test_________file.jpg')

    def test_sanitize_mixed_filename(self):
        """Test filename with mix of valid and invalid characters."""
        filename = "vacation:2024/photo*.jpg"
        result = sanitize_filename(filename)
        self.assertEqual(result, "vacation_2024_photo_.jpg")


class TestDownloadWithRetry(unittest.TestCase):
    """Test the download_with_retry function."""

    @patch('download_memories.requests.get')
    @patch('download_memories.time.sleep')
    def test_successful_download_first_try(self, mock_sleep, mock_get):
        """Test successful download on first attempt."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = download_with_retry('https://example.com/file.jpg')

        self.assertEqual(result, mock_response)
        mock_get.assert_called_once()
        mock_sleep.assert_not_called()

    @patch('download_memories.requests.get')
    @patch('download_memories.time.sleep')
    def test_retry_on_timeout(self, mock_sleep, mock_get):
        """Test retry logic on timeout."""
        # First two calls timeout, third succeeds
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.side_effect = [
            requests.exceptions.Timeout("Timeout 1"),
            requests.exceptions.Timeout("Timeout 2"),
            mock_response
        ]

        result = download_with_retry('https://example.com/file.jpg')

        self.assertEqual(result, mock_response)
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch('download_memories.requests.get')
    @patch('download_memories.time.sleep')
    def test_retry_on_rate_limit(self, mock_sleep, mock_get):
        """Test retry logic on rate limit (429)."""
        mock_response_429 = Mock()
        mock_response_429.status_code = 429

        mock_response_200 = Mock()
        mock_response_200.status_code = 200

        mock_get.side_effect = [mock_response_429, mock_response_200]

        result = download_with_retry('https://example.com/file.jpg')

        self.assertEqual(result, mock_response_200)
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)

    @patch('download_memories.requests.get')
    @patch('download_memories.time.sleep')
    def test_max_retries_exceeded(self, mock_sleep, mock_get):
        """Test that max retries are respected."""
        mock_get.side_effect = requests.exceptions.Timeout("Persistent timeout")

        with self.assertRaises(requests.exceptions.Timeout):
            download_with_retry('https://example.com/file.jpg')

        # Should try MAX_RETRIES times (default 5)
        self.assertEqual(mock_get.call_count, 5)

    @patch('download_memories.requests.get')
    @patch('download_memories.time.sleep')
    def test_exponential_backoff(self, mock_sleep, mock_get):
        """Test that backoff increases exponentially."""
        mock_get.side_effect = [
            requests.exceptions.Timeout("Timeout 1"),
            requests.exceptions.Timeout("Timeout 2"),
            requests.exceptions.Timeout("Timeout 3"),
        ]

        try:
            download_with_retry('https://example.com/file.jpg')
        except:
            pass

        # Verify backoff times: 1, 2, 4 seconds
        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        self.assertEqual(sleep_calls[0], 1)  # 1 * 2^0
        self.assertEqual(sleep_calls[1], 2)  # 1 * 2^1
        self.assertEqual(sleep_calls[2], 4)  # 1 * 2^2


class TestDownloadMemory(unittest.TestCase):
    """Test the download_memory function."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_memory = {
            'url': 'https://example.com/test.jpg',
            'date': '2024-11-15 14:32:10 UTC',
            'type': 'Image',
            'location': 'San Francisco, CA'
        }

    def tearDown(self):
        """Clean up test fixtures."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    @patch('download_memories.download_with_retry')
    def test_download_image_success(self, mock_download):
        """Test successful image download."""
        # Mock response with image data
        mock_response = Mock()
        mock_response.iter_content = Mock(return_value=[b'fake image data'])
        mock_download.return_value = mock_response

        result = download_memory(self.test_memory, self.temp_dir, 1)

        self.assertTrue(result)
        mock_download.assert_called_once()

        # Check that file was created
        files = list(self.temp_dir.glob('*.jpg'))
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].name.startswith('20241115_143210'))

    @patch('download_memories.download_with_retry')
    def test_download_video_success(self, mock_download):
        """Test successful video download."""
        video_memory = self.test_memory.copy()
        video_memory['type'] = 'Video'

        mock_response = Mock()
        mock_response.iter_content = Mock(return_value=[b'fake video data'])
        mock_download.return_value = mock_response

        result = download_memory(video_memory, self.temp_dir, 1)

        self.assertTrue(result)

        # Check that file was created with .mp4 extension
        files = list(self.temp_dir.glob('*.mp4'))
        self.assertEqual(len(files), 1)

    @patch('download_memories.download_with_retry')
    def test_download_zip_extraction(self, mock_download):
        """Test downloading and extracting ZIP files."""
        # Create a fake ZIP file in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr('photo.jpg', b'fake photo data')
            zf.writestr('overlay.png', b'fake overlay data')
        zip_data = zip_buffer.getvalue()

        mock_response = Mock()
        mock_response.iter_content = Mock(return_value=[zip_data])
        mock_download.return_value = mock_response

        result = download_memory(self.test_memory, self.temp_dir, 1)

        self.assertTrue(result)

        # Check that both files were extracted
        files = list(self.temp_dir.glob('*'))
        self.assertEqual(len(files), 2)

        # Check for overlay file
        overlay_files = [f for f in files if 'overlay' in f.name]
        self.assertEqual(len(overlay_files), 1)

    @patch('download_memories.download_with_retry')
    def test_download_failure_tracking(self, mock_download):
        """Test that failures are properly tracked."""
        mock_download.side_effect = Exception("Network error")

        failed_list = []
        result = download_memory(self.test_memory, self.temp_dir, 1, failed_list=failed_list)

        self.assertFalse(result)
        self.assertEqual(len(failed_list), 1)
        self.assertEqual(failed_list[0]['index'], 1)
        self.assertEqual(failed_list[0]['error'], "Network error")
        self.assertEqual(failed_list[0]['url'], self.test_memory['url'])

    @patch('download_memories.download_with_retry')
    def test_duplicate_filename_handling(self, mock_download):
        """Test that duplicate filenames are handled."""
        mock_response = Mock()
        mock_response.iter_content = Mock(return_value=[b'fake image data'])
        mock_download.return_value = mock_response

        # Download same memory twice
        download_memory(self.test_memory, self.temp_dir, 1)
        download_memory(self.test_memory, self.temp_dir, 1)

        # Check that two files were created with different names
        files = list(self.temp_dir.glob('*.jpg'))
        self.assertEqual(len(files), 2)

        # One should have the base name, one should have _1 suffix
        filenames = [f.name for f in files]
        self.assertTrue(any('_1.jpg' in name for name in filenames))

    @patch('download_memories.download_with_retry')
    def test_progress_tracking(self, mock_download):
        """Test that progress is tracked correctly."""
        mock_response = Mock()
        mock_response.iter_content = Mock(return_value=[b'fake data'])
        mock_download.return_value = mock_response

        progress_info = {'completed': 0, 'total': 10}

        download_memory(self.test_memory, self.temp_dir, 1, progress_info=progress_info)

        self.assertEqual(progress_info['completed'], 1)


class TestIntegration(unittest.TestCase):
    """Integration tests for the overall workflow."""

    def test_end_to_end_workflow(self):
        """Test the complete workflow from HTML parsing to download."""
        html_content = """
        <tr><td>2024-11-15 14:32:10 UTC</td><td>Image</td><td>Test Location</td><td><button onclick="downloadMemories('https://example.com/test.jpg', this, true)">Download</button></td></tr>
        """

        with patch('builtins.open', mock_open(read_data=html_content)):
            memories = extract_urls_from_html('test.html')

        self.assertEqual(len(memories), 1)

        memory = memories[0]
        self.assertEqual(memory['date'], '2024-11-15 14:32:10 UTC')
        self.assertEqual(memory['type'], 'Image')
        self.assertEqual(memory['url'], 'https://example.com/test.jpg')

        # Verify filename would be sanitized correctly
        filename = f"{memory['date']}_test.jpg"
        sanitized = sanitize_filename(filename)
        self.assertNotIn(':', sanitized)


def run_tests():
    """Run all tests."""
    unittest.main(argv=[''], verbosity=2, exit=False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
