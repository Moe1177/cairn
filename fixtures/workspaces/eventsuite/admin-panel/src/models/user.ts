import mongoose from "mongoose";
const User = mongoose.models.User || mongoose.model("User", schema);
export default User;
