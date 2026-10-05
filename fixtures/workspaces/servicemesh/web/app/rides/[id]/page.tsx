export default async function Ride({ params }: { params: { id: string } }) {
  const ride = await fetch(`${process.env.NEXT_PUBLIC_GATEWAY_URL}/api/rides/${params.id}`);
  return <pre>{JSON.stringify(await ride.json())}</pre>;
}
