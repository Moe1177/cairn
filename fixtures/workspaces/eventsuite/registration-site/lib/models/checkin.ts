import mongoose from "mongoose";
const CheckIn = mongoose.models.CheckIn || mongoose.model("CheckIn", schema);
export default CheckIn;
