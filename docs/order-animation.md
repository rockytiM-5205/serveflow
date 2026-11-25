# The order animation

On the order page (`customer/order.html`) the customer sees their order as a picture, not just a list.

**The plate.** Each thing they ordered (up to five; "+ 2 more" beyond that) is shown as a small dish. The dishes fly in from different sides, bounce onto the plate and swirl together, with a small badge for any quantity above one.

**Which picture each dish gets.** Nothing has to be drawn or added by hand when a restaurant sells something new. For every item, the first of these that applies is used:

1. **Its own photo**, if the menu item has one, in a round frame (the drawing shows until the photo has loaded, and stays if it can't).
2. **The picture the restaurant chose** for it: in the dashboard's menu editor, "Picture on the order plate" (rice, meat, fish, plantain, swallow, soup, drink, dessert, eggs, salad, bread, something else). New items start on *Automatic*.
3. **What its name says** ("Jollof rice" is rice, "Chicken suya" is meat).
4. **What its menu category says** ("Drinks", "Soups"), for names the page doesn't recognise.
5. **A covered dish whose colour is made from its name**, so every unknown dish still looks its own, and the same every time.

Only the restaurant's own uploads and https pictures are ever used. The choice is saved on the menu item (`MenuItem.dish_kind`); the order page receives each line's `image_url`, `dish_kind` and `category`.

**The story, step by step**

| Step | What happens |
|---|---|
| Order placed | The dishes gather on the plate |
| Confirmed | A green tick pops onto the plate |
| Preparing | Steam rises, the plate bobs, the food is gently stirred |
| Ready | A cover lowers over the plate, lifts away, a glow breathes around it and sparkles twinkle |
| Completed | One shower of confetti, then calm; every tick is green |
| Cancelled or rejected | A quiet grey plate with a cross, no motion |

**The ticks.** Under the plate, five steps with a tick for each. A small plate token rides along the line from one green tick to the next as the status moves, the line fills behind it, and each tick draws itself
as the token reaches it.

**When it plays.** The first time the page opens it plays from the start (so a customer opening the link mid-preparation still sees the food arrive). When the live updates move the order forward it plays only the new
step. Updates that change nothing leave the picture still. People whose device asks for reduced motion get the finished picture with no movement. Screen readers get the same information as before: the headline, the status
badges and an ordered list of steps with the current one marked.

**Where the code is.** `customer/js/order-scene.js` (decisions and drawing), `customer/css/order-scene.css` (all motion, the base state of every part is the finished picture), `tests/order-scene.test.mjs`.
It uses only colours and sizes that both designs define, so it looks right in classic and in premium.
To watch it frame by frame: `python tools/visual_check.py anim` (saves six frames per order status to `tools/visual_out/`).
