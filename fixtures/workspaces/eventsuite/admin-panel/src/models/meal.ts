import mongoose from "mongoose";
const Meal = mongoose.models.Meal || mongoose.model("Meal", schema);
export default Meal;
