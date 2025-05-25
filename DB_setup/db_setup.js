// db_setup.js

print("🚀 Starting database initialization...");

// Switch to ramesh DB
db = db.getSiblingDB("ramesh");

// Create login_info if not exists
if (!db.getCollectionNames().includes("login_info")) {
    db.createCollection("login_info");
    db.login_info.insertOne({
        username: "admin",
        password: "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9"  // hash of "admin123"
    });
    print("✅ login_info collection created");
    
    // Create index for username
    db.login_info.createIndex({ "username": 1 }, { unique: true });
} else {
    print("ℹ️ login_info collection already exists");
}

// Create products collection if not exists
if (!db.getCollectionNames().includes("products")) {
    db.createCollection("products");
    print("✅ products collection created");
    
    // Create indexes for better performance
    db.products.createIndex({ "Product_unique_ID": 1 }, { unique: true });
    db.products.createIndex({ "published_status": 1 });
    db.products.createIndex({ "Publish": 1 });
    db.products.createIndex({ "Publish_time": 1 });
} else {
    print("ℹ️ products collection already exists");
}

// Create published_products collection if not exists
if (!db.getCollectionNames().includes("published_products")) {
    db.createCollection("published_products");
    print("✅ published_products collection created");
    
    // Create indexes for better query performance
    db.published_products.createIndex({ "product_id": 1 });
    db.published_products.createIndex({ "publish_date": -1 });
    db.published_products.createIndex({ "published_price": 1 });
    db.published_products.createIndex({ "published_channels": 1 });
    
    // Create compound indexes for common queries
    db.published_products.createIndex({ 
        "product_id": 1, 
        "publish_date": -1 
    });
} else {
    print("ℹ️ published_products collection already exists");
}

// Create configuration collection if not exists
if (!db.getCollectionNames().includes("config")) {
    db.createCollection("config");
    
    // Insert default configuration
    db.config.insertOne({
        "type": "notification_settings",
        "telegram_enabled": true,
        "whatsapp_enabled": true,
        "email_enabled": false,
        "created_at": new Date()
    });
    
    print("✅ config collection created with default settings");
} else {
    print("ℹ️ config collection already exists");
}

// Validate collections and indexes
print("\n🔍 Validating database setup...");

let collections = db.getCollectionNames();
print(`\nFound ${collections.length} collections:`);
collections.forEach(collection => {
    let count = db[collection].count();
    let indexes = db[collection].getIndexes();
    print(`- ${collection}: ${count} documents, ${indexes.length} indexes`);
});

print("\n✅ Database initialization complete!");
