# applyTextStyle examples (hand-checked; no JS runner)

Format: `quotes/brackets` : input -> output

1. smart/corner : `"Hello," she said.` -> `“Hello,” she said.`
2. smart/corner : `He said "go"` -> `He said “go”` (closing quote at end: next is "")
3. smart/corner : `don't` -> `don’t` (letter on both sides)
4. smart/corner : `the dogs' bones` -> `the dogs’ bones` (prev letter, next space: closing)
5. smart/corner : `'tis not` -> `‘tis not` (known limitation: leading apostrophe reads as opening)
6. smart/corner : `She said 'hi'.` -> `She said ‘hi’.`
7. smart/corner : `("yes")` -> `(“yes”)` (after "(" opening; after letter closing)
8. regular/corner : `“Hi,” ‘you’` -> `"Hi," 'you'`
9. regular/corner : `It’s` -> `It's`
10. regular/corner : `[Skill] 『Art』` -> `【Skill】 【Art】`
11. regular/regular : `【Level Up】` -> `[Level Up]`
12. regular/semicorner : `[Item] 【Item】` -> `『Item』 『Item』`
13. smart/regular : `"[Heaven's Gate]"` -> `“[Heaven’s Gate]”`
14. regular/corner : `(parens) {braces} <angle>` -> unchanged
15. smart/corner : `—"Run!"` -> `—“Run!”` (after dash: opening)
