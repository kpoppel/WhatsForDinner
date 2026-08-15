This is a description of the project and its requirements. It is OpenSource.

# Purpose of the proejct
Figuring our what is for dinner is often hard enough in a busy day, where the familty has different schedules, some days need to produce meals for 2 days, shopping needs to be done, and so on.
Oftentimes one in the familty ends up trying to fit it all together, because it is just easier, and because if one does it, the rest need not worry.  Writing the shpping list on a piece of paper works, but it is difficult to see it if going shopping after work.

This project is an attempt at solving some core needs using software:
- Deciding what to have for dinner during a 1 week period
- Easy access to a common shopping list when on the go

A great many other projects hae been created around the same topic for sure, but it is also fun to build something new.

# Requirements

## Stage 1

### Backend
- There is a FastAPI backend service running in a Docker container
- The backend will communicate with Tandoor Recipes API for retrieving recipes, recipe tag options, creating/modifying meal plans, access to the shopping list read/write
- The backend will translate the Tandoor data streams into the needs of the frontend app of this project
- There is a rudimentary inspection webapp for direct REST API inspection

### Frontend
- A very simple user app is accessible. Just plain HTML and JS to illustrate user interaction
- User interactions:
  - Set tags to retrieve recipes for (to get only wanted candidates)
  - Create shopping list frm recipes
  - Add items to shipping list
  - Remove items from shopping list

## Stage 2 - undecided
### Backend
### Frontend


