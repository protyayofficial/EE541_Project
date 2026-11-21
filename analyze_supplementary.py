"""Rebuild supplementary run summaries, paired comparisons and figures."""
import argparse
from supplementary_studies import analyze

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory')
    analyze(parser.parse_args().directory)
