import mongoose from "mongoose";
const VerifiedEmail = mongoose.models.Verified_Email || mongoose.model("Verified_Email", schema);
export default VerifiedEmail;
