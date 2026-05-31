using Sparkgeo.PrescientSdk;

var client = new PrescientClient(new PrescientClientOptions
{
    EndpointUrl = "https://api.example.com",
    ClientId = "test-client-id",
    AuthUrl = "https://login.microsoftonline.com",
    TenantId = "test-tenant-id",
});

Console.WriteLine($"EndpointUrl    : {client.Settings.EndpointUrl}");
Console.WriteLine($"StacCatalogUrl : {client.StacCatalogUrl}");
Console.WriteLine("✓ .NET smoke test passed");
