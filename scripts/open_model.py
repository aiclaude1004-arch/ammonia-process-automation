"""Open an explicitly selected model copy; never launch a campaign."""
from pathlib import Path
import argparse, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aspen_automation import AspenSession

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', type=Path, required=True)
    args = parser.parse_args()
    with AspenSession() as session:
        session.open(args.backup)
        print('BLOCKS:', session.names(r'\Data\Blocks'))
        print('STREAMS:', session.names(r'\Data\Streams'))
        input('Press Enter to close this independent document. ')

if __name__ == '__main__': main()
