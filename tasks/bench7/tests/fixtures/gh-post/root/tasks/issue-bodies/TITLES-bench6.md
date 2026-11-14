# Bench-6 issue titles (test fixture)

Creation order, slug, and the title to pass to `gh issue create --title`.

| order | slug | title | length |
|---|---|---|---|
| 1 | alpha | A node stopped between two writes can never start again | 55 |
| 2 | beta | A shortened title for the beta defect | 37 |
| 3 | gamma | The gamma defect follows from the alpha defect | 46 |
| 4 | delta | The delta body names an issue nobody posted | 43 |
| 5 | epsilon | The epsilon body opens with a different heading | 47 |
| 6 | period | This title ends in a period. | 28 |
| 7 | toolong | This title runs on and on past the limit of one hundred and twenty characters that the posting script enforces on every title | 125 |
| 8 | dirty | A body with a line the lint refuses | 35 |
| 9 | pipe | A title with a \| pipe in it | 27 |
| 10 | empty | An issue whose body is empty | 28 |
| 11 | toolongbody | An issue whose body is too long | 31 |

## Verbatim H1s that were shortened

- beta (145): The beta defect has a long verbatim heading that runs past the hundred and twenty character limit, so the table carries a shortened title instead
