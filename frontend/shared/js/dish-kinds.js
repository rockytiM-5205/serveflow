/* The pictures a restaurant can choose for an item on the customer's order plate (when the item has no photo of its own).
 * Keep in step with DishKind in backend/apps/menu/models.py. "" means: work it out from the name and category. */
export const DISH_OPTIONS = [
  { value: "rice", label: "Rice or pasta" },
  { value: "meat", label: "Meat or chicken" },
  { value: "fish", label: "Fish or seafood" },
  { value: "plantain", label: "Plantain, yam or chips" },
  { value: "swallow", label: "Swallow (pounded yam, amala, eba)" },
  { value: "soup", label: "Soup or stew" },
  { value: "drink", label: "Drink" },
  { value: "dessert", label: "Dessert" },
  { value: "egg", label: "Eggs" },
  { value: "veg", label: "Salad or vegetables" },
  { value: "bread", label: "Bread, snack or pastry" },
  { value: "dish", label: "Something else" },
];
export const DISH_KINDS = DISH_OPTIONS.map((o) => o.value);
