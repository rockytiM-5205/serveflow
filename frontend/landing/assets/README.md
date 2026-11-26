# Landing page pictures

All pictures are WebP (small and fast). The page still works if one is missing: that picture's frame simply disappears.
Use pictures you own or have licensed.

| File | Used for |
|---|---|
| `hero-food.webp` | The plate in the hero (transparent background) and in the "Special requests" tile |
| `dine-in.webp` | "Dine-in ordering" card |
| `dine-in-guests.webp` | "Dine-in" tile |
| `pickup.webp` | "Scheduled pickup" card and tile |
| `team.webp` | "Restaurant management" card and the "Built for restaurants" section |
| `screens/customer-menu.png`, `screens/orders-queue.png`, `screens/payments-to-check.png` | Optional real screenshots. The "Inside ServeFlow" section stays hidden until at least one exists. Take them from your running app with test data (no real customer names or phone numbers) |

To convert a new picture: `python -c "from PIL import Image; Image.open('in.jpg').convert('RGB').save('out.webp','WEBP',quality=80,method=6)"`
