package smoke;

import com.sparkgeo.prescient.PrescientClient;
import com.sparkgeo.prescient.PrescientClientOptions;

public class SmokeTest {
    public static void main(String[] args) {
        PrescientClient client = new PrescientClient(
            PrescientClientOptions.builder()
                .envFile("/workspace/smoke-tests/config.env")
                .build()
        );

        System.out.println("endpointUrl    : " + client.getSettings().getEndpointUrl());
        System.out.println("stacCatalogUrl : " + client.getStacCatalogUrl());
        System.out.println("✓ Java smoke test passed");
    }
}
