#!/usr/bin/env python3
"""
DIAGNOSTIC SCRIPT: Identify why dry-run size shows 0.00 MB
"""
import tempfile
import os
import subprocess
from autobackup.core.rsync_engine import RsyncEngine

print("=" * 70)
print("ROOT CAUSE ANALYSIS: Dry Run Size Calculation Bug")
print("=" * 70)

# Create test environment
test_dir = tempfile.mkdtemp(prefix='diag_dry_run_')
source = os.path.join(test_dir, 'source')
dest = os.path.join(test_dir, 'dest')
os.makedirs(source)
os.makedirs(dest)

# Create test files with KNOWN sizes
test_files = {
    'file1.txt': 'X' * (10 * 1024),      # 10 KB
    'file2.txt': 'Y' * (5 * 1024 * 1024), # 5 MB
    'file3.txt': 'Z' * 1024,             # 1 KB
}

expected_total_bytes = sum(len(content) for content in test_files.values())

print(f"\n1. TEST ENVIRONMENT SETUP")
print(f"   Source: {source}")
print(f"   Destination: {dest}")
print(f"\n   Created files:")

for filepath, content in test_files.items():
    full_path = os.path.join(source, filepath)
    with open(full_path, 'w') as f:
        f.write(content)
    actual_size = os.path.getsize(full_path)
    print(f"      • {filepath}: {actual_size:,} bytes")

print(f"\n   EXPECTED TOTAL: {expected_total_bytes:,} bytes ({expected_total_bytes / (1024**2):.2f} MB)")

# Now run rsync dry-run and capture output
print(f"\n2. RUNNING RSYNC DRY-RUN")
engine = RsyncEngine()
rsync_stats = engine.run_rsync(source, dest, [], dry_run=True)

print(f"\n3. PARSED RSYNC STATS")
print(f"   total_file_size: {rsync_stats.get('total_file_size', 'NOT FOUND')} bytes")
print(f"   number_of_files: {rsync_stats.get('number_of_files', 'NOT FOUND')}")
print(f"   files_transferred: {rsync_stats.get('files_transferred', 'NOT FOUND')}")
print(f"   total_size_bytes: {rsync_stats.get('total_size_bytes', 'NOT FOUND')}")

# Check if the value is 0
total_file_size = rsync_stats.get('total_file_size', 0)
if total_file_size == 0:
    print(f"\n   ⚠️  PROBLEM FOUND: total_file_size is 0!")
    print(f"   Expected: {expected_total_bytes:,} bytes")
    print(f"   Got: {total_file_size} bytes")
else:
    print(f"\n   ✅ Size correctly parsed: {total_file_size:,} bytes")

# Now let's see what rsync actually outputs
print(f"\n4. RAW RSYNC OUTPUT")
print(f"   Running: rsync -aHv --dry-run --stats {source}/ {dest}/\n")
result = subprocess.run(
    ['rsync', '-aHv', '--dry-run', '--stats', f'{source}/', f'{dest}/'],
    capture_output=True,
    text=True
)
rsync_output = result.stdout + result.stderr
print("   Last 20 lines of rsync output:")
print("   " + "\n   ".join(rsync_output.splitlines()[-20:]))

# Calculate size manually using filesystem
print(f"\n5. MANUAL FILESYSTEM CALCULATION")
manual_total = 0
for root, dirs, files in os.walk(source):
    for file in files:
        filepath = os.path.join(root, file)
        manual_total += os.path.getsize(filepath)
print(f"   Manual calculation (os.walk + getsize): {manual_total:,} bytes")
print(f"   This should equal expected total: {expected_total_bytes:,} bytes")

if manual_total == expected_total_bytes:
    print(f"   ✅ Manual calculation matches expected size!")
else:
    print(f"   ❌ Manual calculation mismatch!")

# Cleanup
import shutil
shutil.rmtree(test_dir)

print(f"\n" + "=" * 70)
print("DIAGNOSIS COMPLETE")
print("=" * 70)
