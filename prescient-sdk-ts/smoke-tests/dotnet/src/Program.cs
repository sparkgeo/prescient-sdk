using Sparkgeo.PrescientSdk;

var client = new PrescientClient(new PrescientClientOptions
{
    EnvFile = "/workspace/smoke-tests/config.env",
});

Console.WriteLine($"EndpointUrl    : {client.Settings.EndpointUrl}");
Console.WriteLine($"StacCatalogUrl : {client.StacCatalogUrl}");
Console.WriteLine("✓ .NET smoke test passed");
