package main

func main() {
	s := grpc.NewServer()
	pb.RegisterGeoServiceServer(s, &server{})
}
