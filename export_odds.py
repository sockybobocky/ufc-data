"""Small odds-only entry point; failed status must still be publishable."""
import os
from odds_export import update

def collect(session,key,root='.'):
    return update(session,key,root)

def main():
    import requests
    with requests.Session() as session:
        result=collect(session,os.environ.get('ODDS_API_KEY',''))
    print('Odds collection succeeded.' if result['state']=='success' else 'Odds collection failed; status recorded and prior prices retained.')
    # The workflow publishes the failure status before marking the job failed.
    return 0

if __name__=='__main__':raise SystemExit(main())
