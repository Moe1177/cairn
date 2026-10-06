import mongoose from "mongoose";
const QrCodeMapping = mongoose.models.QrCodeMapping || mongoose.model("QrCodeMapping", schema);
export default QrCodeMapping;
