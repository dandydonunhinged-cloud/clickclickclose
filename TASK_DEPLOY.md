# TASK: Deploy Click Click Close

## What
Deploy `C:/DandyDon/investor_site/` to GitHub Pages at `clickclickclose.click`

## How
1. `cd C:/DandyDon/investor_site`
2. `git add .` (gitignore already excludes research files)
3. `git commit -m "Initial site deploy"`
4. `gh repo create dandydonunhinged-cloud/clickclickclose --public --source=. --push`
5. `gh api repos/dandydonunhinged-cloud/clickclickclose/pages -X POST -f source.branch=master -f source.path=/`
6. Go to domain registrar, set CNAME for `clickclickclose.click` → `dandydonunhinged-cloud.github.io`
7. Add CNAME file: `echo "clickclickclose.click" > CNAME && git add CNAME && git commit -m "Add CNAME" && git push`

## Notes
- `gh` is authenticated as `dandydonunhinged-cloud`
- netlify.toml exists but Netlify CLI is not installed — GitHub Pages is simpler
- CSS path: index.html uses `styles.css`, other pages use `css/styles.css` — both files exist, both work
- No build step needed, pure static HTML/CSS/JS

## Status
UNSTARTED — assign to a builder Claude tab
