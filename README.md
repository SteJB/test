# Hours worked by income level (CPS ASEC)

`cps_hours_by_income.py` downloads the Census Bureau's CPS Annual Social and Economic
Supplement (ASEC) public-use file and graphs average usual weekly hours worked by income:

| Chart | Unit | Income measure | Hours measure | Sample |
|---|---|---|---|---|
| `output/hours_by_household_income.png` | Household | Total household income (`HTOTVAL`) | Sum of `HRSWK` across all members who worked | Interviewed households with at least one worker |
| `output/hours_by_individual_income.png` | Person | Total personal income (`PTOTVAL`) | `HRSWK` | People who worked last year (`HRSWK > 0`) |

`HRSWK` is usual hours worked per week in weeks worked during the previous calendar year,
so hours and income cover the same period. Averages use the ASEC supplement weights
(`HSUP_WGT` for households, `MARSUPWT` for people).

The matching CSVs in `output/` also hold average annual hours (`HRSWK × WKSWORK`),
unweighted cell counts, and a household version that includes households with no workers
(the `*_all_households` columns).

## Run

```sh
pip install -r requirements.txt
python cps_hours_by_income.py               # ASEC 2025 (income and hours for 2024)
python cps_hours_by_income.py --year 2024   # an earlier release
python cps_hours_by_income.py --zip ~/Downloads/asecpub25csv.zip   # use a file you downloaded
```

The download comes from
`https://www2.census.gov/programs-surveys/cps/datasets/<year>/march/asecpub<yy>csv.zip`
and is cached in `data/`.
