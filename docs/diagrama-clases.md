# Diagrama de clases de análisis (H07)

Modelo de análisis **Interfaz (`<<boundary>>`) – Control (`<<control>>`) – Entidad (`<<entity>>`)** para todos los módulos de negocio de TexCore ERP, con su correspondencia verificada frente a las clases reales en React (Frontend) y Django / DRF (Backend).

---

## 1. Seguridad, Inventario y Compras

```mermaid
classDiagram
    class LoginPage {
        <<boundary>>
    }
    class UsersPage {
        <<boundary>>
    }
    class InventoryPage {
        <<boundary>>
    }
    class PurchaseOrdersPage {
        <<boundary>>
    }

    class AuthController {
        <<control>>
        +obtainToken()
        +refreshToken()
        +requestPasswordReset()
    }
    class SecurityController {
        <<control>>
        +hasPermission()
        +recordAccess()
        +logAudit()
    }
    class InventoryService {
        <<control>>
        +registerEntry()
        +createOutputOrder()
        +cancelOutputOrder()
    }
    class PurchasingService {
        <<control>>
        +createPurchaseOrder()
        +approvePurchaseOrder()
        +receiveMerchandise()
    }

    class CustomUser {
        <<entity>>
        +email
        +is_active
        +failed_login_attempts
    }
    class Role {
        <<entity>>
        +code
        +name
    }
    class Producto {
        <<entity>>
        +codigo
        +stock_actual
        +costo_promedio
    }
    class Movimiento {
        <<entity>>
        +tipo
        +cantidad
        +saldo_antes
        +saldo_despues
    }
    class OrdenCompra {
        <<entity>>
        +codigo
        +estado
    }

    LoginPage --> AuthController
    UsersPage --> SecurityController
    InventoryPage --> InventoryService
    PurchaseOrdersPage --> PurchasingService

    AuthController --> CustomUser
    SecurityController --> CustomUser
    SecurityController --> Role
    InventoryService --> Producto
    InventoryService --> Movimiento
    PurchasingService --> OrdenCompra
    PurchasingService --> InventoryService
```

---

## 2. Referencias, Producción y Lavandería

```mermaid
classDiagram
    class ReferencesPage {
        <<boundary>>
    }
    class OrdersPage {
        <<boundary>>
    }
    class MonitorPage {
        <<boundary>>
    }
    class OrderSettlementPage {
        <<boundary>>
    }
    class LaundryRemissionPage {
        <<boundary>>
    }
    class LaundryReceptionPage {
        <<boundary>>
    }

    class FichaService {
        <<control>>
        +saveTechnicalSheet()
        +simulateMaterial()
    }
    class ProductionController {
        <<control>>
        +createOrder()
        +transitionStage()
        +assignResource()
        +calculateOrderCosts()
    }
    class LaundryController {
        <<control>>
        +createRemission()
        +createReception()
    }

    class Referencia {
        <<entity>>
        +codigo
        +estado
    }
    class Variante {
        <<entity>>
        +talla
        +color
    }
    class OrdenProduccion {
        <<entity>>
        +codigo
        +cantidad
    }
    class Lote {
        <<entity>>
        +codigo
        +cantidad
        +estado_inventario
    }
    class EtapaLote {
        <<entity>>
        +etapa
        +estado
        +tiempo_acumulado_seg
    }
    class TarifaManoObra {
        <<entity>>
        +etapa
        +costo_minuto
        +vigente_desde
    }
    class RemisionLavanderia {
        <<entity>>
        +codigo
        +estado
    }
    class RecepcionLavanderia {
        <<entity>>
        +codigo
        +factura_remision_externa
    }

    ReferencesPage --> FichaService
    OrdersPage --> ProductionController
    MonitorPage --> ProductionController
    OrderSettlementPage --> ProductionController
    LaundryRemissionPage --> LaundryController
    LaundryReceptionPage --> LaundryController

    FichaService --> Referencia
    FichaService --> Variante
    ProductionController --> OrdenProduccion
    ProductionController --> Lote
    ProductionController --> EtapaLote
    ProductionController --> TarifaManoObra
    LaundryController --> RemisionLavanderia
    LaundryController --> RecepcionLavanderia
    LaundryController --> Lote
```

---

## 3. Calidad, Producto Terminado, Ventas, Envíos y Reportes

```mermaid
classDiagram
    class InspectionsPage {
        <<boundary>>
    }
    class EntryAdjustmentPages {
        <<boundary>>
    }
    class SaleCarteraPages {
        <<boundary>>
    }
    class GuidesDispatchPages {
        <<boundary>>
    }
    class ReportsPage {
        <<boundary>>
    }

    class QualityService {
        <<control>>
        +registerInspection()
    }
    class FinishedStockService {
        <<control>>
        +registerEntry()
        +registerAdjustment()
        +lockStock()
    }
    class SalesInvoicingService {
        <<control>>
        +issueInvoice()
        +confirmPayment()
        +registerReturn()
        +calculateFactoryCost()
    }
    class ShippingTrackingService {
        <<control>>
        +assignGuide()
        +createDispatchRelation()
        +refreshTracking()
    }
    class ReportsAnalyticsService {
        <<control>>
        +buildManagementReport()
        +refreshMaterializedViews()
    }

    class Inspeccion {
        <<entity>>
        +codigo
        +aptas
        +marras
    }
    class StockTerminado {
        <<entity>>
        +cantidad
    }
    class MovimientoTerminado {
        <<entity>>
        +tipo
        +cantidad
        +saldo_antes
        +saldo_despues
    }
    class FacturaVenta {
        <<entity>>
        +numero
        +estado
        +estado_cobro
        +total
    }
    class SaldoFinanciero {
        <<entity>>
        +nombre
        +saldo_actual
    }
    class Guia {
        <<entity>>
        +numero_guia
        +estado
        +valor_flete
    }

    InspectionsPage --> QualityService
    EntryAdjustmentPages --> FinishedStockService
    SaleCarteraPages --> SalesInvoicingService
    GuidesDispatchPages --> ShippingTrackingService
    ReportsPage --> ReportsAnalyticsService

    QualityService --> Inspeccion
    FinishedStockService --> StockTerminado
    FinishedStockService --> MovimientoTerminado
    SalesInvoicingService --> FacturaVenta
    SalesInvoicingService --> SaldoFinanciero
    SalesInvoicingService --> FinishedStockService
    ShippingTrackingService --> Guia
    ShippingTrackingService --> SalesInvoicingService
    ReportsAnalyticsService --> FacturaVenta
    ReportsAnalyticsService --> Guia
```

---

## 4. Correspondencia exacta con el código del sistema

| Módulo | Clases Interfaz (`frontend/src/components/`) | Clases Control (`backend/apps/*/views.py`, `services.py`) | Clases Entidad (`backend/apps/*/models.py`) |
|---|---|---|---|
| **Seguridad (`users`)** | `Login.jsx`, `UsersPage.jsx`, `RolesPage.jsx`, `AccessLogsPage.jsx`, `AuditLogsPage.jsx` | `CustomTokenObtainPairView`, `UserListCreateView`, `HasPermission`, `password_reset` | `CustomUser`, `Role`, `ModulePermission`, `RolePermission`, `TokenRecuperacion`, `Acceso`, `Auditoria` |
| **Inventario (`inventory`)** | `InventoryPage.jsx`, `CatalogPage.jsx`, `SuppliersPage.jsx` | `IngresoView`, `OrdenSalidaListCreateView`, `inventory.services` | `Proveedor`, `Producto`, `Movimiento`, `OrdenSalida`, `OrdenLinea`, `Evidencia`, `Consecutivo` |
| **Compras (`purchasing`)** | `PurchaseOrdersPage.jsx`, `MerchandiseReceptionPage.jsx` | `OrdenCompraListCreateView`, `OrdenCompraAprobarView`, `purchasing.services` | `OrdenCompra`, `OrdenCompraLinea`, `RecepcionCompra`, `RecepcionCompraLinea` |
| **Referencias (`references`)** | `ReferencesPage.jsx`, `FichaModal.jsx` | `ReferenciaListCreateView`, `FichaTecnicaView`, `fichas.py` | `Referencia`, `Variante`, `ReferenciaImagen`, `FichaTecnica`, `FichaTecnicaLinea` |
| **Producción (`production`)** | `OrdersPage.jsx`, `MonitorPage.jsx`, `ResourcesPage.jsx`, `OrderSettlementPage.jsx` | `OrdenProduccionListCreateView`, `LoteAccionView`, `OrdenProduccionCostosView`, `tracking.py`, `costing.py`, `monitor.py`, `resources.py` | `OrdenProduccion`, `Lote`, `LoteTalla`, `EtapaLote`, `EventoEtapa`, `Operario`, `Maquina`, `AsignacionEtapa`, `TarifaManoObra` |
| **Lavandería (`production`)** | `LaundryRemissionPage.jsx`, `LaundryReceptionPage.jsx` | `RemisionLavanderiaListCreateView`, `RecepcionLavanderiaListCreateView`, `remisiones_services.py`, `recepcion_services.py` | `RecetaLavado`, `RemisionLavanderia`, `RemisionLote`, `RecepcionLavanderia`, `RecepcionLote` |
| **Calidad (`quality`)** | `DefectsPage.jsx`, `InspectionsPage.jsx` | `DefectoListCreateView`, `InspeccionListCreateView`, `quality.services` | `TipoDefecto`, `Inspeccion`, `MarraDetalle` |
| **Producto Terminado (`finished`)** | `EntryPage.jsx`, `StockPage.jsx`, `AdjustmentPage.jsx`, `MovementsPage.jsx` | `IngresoListCreateView`, `AjusteListCreateView`, `finished.services`, `adjustments.py` | `IngresoTerminado`, `IngresoLinea`, `StockTerminado`, `MovimientoTerminado`, `AjusteTerminado`, `AjusteLinea` |
| **Ventas y Cartera (`sales`)** | `SalesPanel.jsx`, `SalePage.jsx`, `InvoicesPage.jsx`, `CarteraPage.jsx`, `PricesPage.jsx`, `ClientsPage.jsx` | `FacturaListCreateView`, `FacturaConciliarView`, `PrecioAplicarCostoView`, `sales.invoicing`, `sales.pricing` | `Cliente`, `PrecioReferencia`, `HistorialPrecioReferencia`, `FacturaVenta`, `DetalleVenta`, `SaldoFinanciero`, `MovimientoCartera` |
| **Envíos (`shipping`)** | `ShippingPanel.jsx`, `GuidesPage.jsx`, `PendingPage.jsx`, `DispatchPage.jsx` | `GuiaRastrearView`, `RelacionListCreateView`, `shipping.services`, `tracking.py`, `track123.py` | `RelacionDespacho`, `Guia`, `EventoGuia` |
| **Reportes (`reports`)** | `ReportsPage.jsx` | `ReporteGerencialView`, `ReporteRefrescarVistasView`, `reports.services` | `VistaProduccionOrden`, `VistaVentasReferencia` *(vistas SQL `managed = False`)* |
