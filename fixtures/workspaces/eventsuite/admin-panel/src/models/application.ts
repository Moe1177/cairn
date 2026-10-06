import mongoose from "mongoose";
const Application = mongoose.models.Applications || mongoose.model("Applications", schema);
export default Application;
