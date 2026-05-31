package smoke;

import com.sparkgeo.prescient.PrescientClient;
import com.sparkgeo.prescient.PrescientClientOptions;

public class SmokeTest {
    public static void main(String[] args) {
        PrescientClient client = new PrescientClient(
            PrescientClientOptions.builder()
                .endpointUrl("https://api.example.com")
                .clientId("test-client-id")
                .authUrl("https://login.microsoftonline.com")
                .tenantId("test-tenant-id")
                .build()
        );

        System.out.println("endpointUrl    : " + client.getSettings().getEndpointUrl());
        System.out.println("stacCatalogUrl : " + client.getStacCatalogUrl());
        System.out.println("✓ Java smoke test passed");
    }
}
