 import subprocess
import re

def test_rocm_parsing():
    # Test utilization
    result = subprocess.run(["rocm-smi", "--showuse"], capture_output=True, text=True)
    print("=== Utilization Output ===")
    print(result.stdout)
    print("=== Utilization Return Code ===")
    print(result.returncode)
    
    # Test memory
    result = subprocess.run(["rocm-smi", "--showmemuse"], capture_output=True, text=True)
    print("\n=== Memory Output ===")
    print(result.stdout)
    
    # Test power
    result = subprocess.run(["rocm-smi", "--showpower"], capture_output=True, text=True)
    print("\n=== Power Output ===")
    print(result.stdout)

if __name__ == "__main__":
    test_rocm_parsing()
