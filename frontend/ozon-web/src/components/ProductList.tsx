import React, { useState, useEffect, useCallback } from 'react';

interface Product {
  id: number;
  product_id: number;
  name: string;
  offer_id: string;
  price: number;
  images: string[];
  image_url: string;
  cost: number;
  category: string;
  commission_amount: number;
  profit?: number;
  margin?: number;
  roi?: number;
  profit_percent?: number;
  ad_cost?: number;
  return_cost?: number;
}

interface Pagination {
  page: number;
  limit: number;
  total: number;
}

interface ProductListProps {
  products: Product[];
  onCostSave: (productId: string, cost: number) => Promise<void>;
  onBulkCostUpdate: (productIds: string[], cost: number) => Promise<void>;
  isLoading?: boolean;
  onFetchPage?: (page: number, limit: number) => Promise<void>;
  pagination?: Pagination;
}

const ProductList: React.FC<ProductListProps> = ({ 
  products, 
  onCostSave, 
  onBulkCostUpdate,
  isLoading = false,
  onFetchPage,
  pagination
}) => {
  // Определяем, используем ли серверную или клиентскую пагинацию
  const isServerPagination = !!onFetchPage && !!pagination;
  
  // Состояние для пагинации
  const [currentPage, setCurrentPage] = useState(pagination?.page || 1);
  const [itemsPerPage, setItemsPerPage] = useState(pagination?.limit || 20);
  const [totalItems, setTotalItems] = useState(pagination?.total || 0);
  
  // Состояние для редактирования и сохранения себестоимости
  const [productCosts, setProductCosts] = useState<Record<string, number>>({});
  const [savedCosts, setSavedCosts] = useState<Record<string, number>>({});
  const [savingCost, setSavingCost] = useState<Record<string, boolean>>({});
  
  // Состояние для массового редактирования
  const [selectedProducts, setSelectedProducts] = useState<string[]>([]);
  const [bulkCost, setBulkCost] = useState<string>('');
  const [isBulkUpdating, setIsBulkUpdating] = useState(false);
  
  // Состояние для поиска и фильтрации
  const [searchTerm, setSearchTerm] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  
  // Состояние для отслеживания загрузки пагинации
  const [isPageLoading, setIsPageLoading] = useState(false);
  
  // Обновляем состояние компонента при изменении пагинации из пропсов
  useEffect(() => {
    if (pagination) {
      setCurrentPage(pagination.page);
      setItemsPerPage(pagination.limit);
      setTotalItems(pagination.total);
    }
  }, [pagination]);
  
  // При загрузке продуктов инициализируем состояние себестоимости
  useEffect(() => {
    if (!isLoading) {
      const costsMap: Record<string, number> = {};
      products.forEach(product => {
        costsMap[product.offer_id] = product.cost;
      });
      setProductCosts(costsMap);
      setSavedCosts(costsMap);
      
      // Если не используем серверную пагинацию, обновляем общее количество товаров
      if (!isServerPagination) {
        setTotalItems(products.length);
      }
    }
  }, [products, isLoading, isServerPagination]);
  
  // Обработчик изменения себестоимости товара
  const handleCostChange = (productId: string, value: string) => {
    const cost = parseFloat(value) || 0;
    setProductCosts(prev => ({
      ...prev,
      [productId]: cost
    }));
  };
  
  // Обработчик сохранения себестоимости товара
  const handleCostSave = async (productId: string) => {
    const cost = productCosts[productId];
    
    setSavingCost(prev => ({
      ...prev,
      [productId]: true
    }));
    
    try {
      await onCostSave(productId, cost);
      setSavedCosts(prev => ({
        ...prev,
        [productId]: cost
      }));
    } finally {
      setSavingCost(prev => ({
        ...prev,
        [productId]: false
      }));
    }
  };
  
  // Проверка, была ли изменена себестоимость товара
  const isCostChanged = (productId: string) => {
    return productCosts[productId] !== savedCosts[productId];
  };
  
  // Обработчик выбора товара для массового редактирования
  const handleProductSelect = (productId: string, isSelected: boolean) => {
    if (isSelected) {
      setSelectedProducts(prev => [...prev, productId]);
    } else {
      setSelectedProducts(prev => prev.filter(id => id !== productId));
    }
  };
  
  // Обработчик изменения значения для массового редактирования
  const handleBulkCostChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setBulkCost(e.target.value);
  };
  
  // Обработчик применения массового редактирования
  const handleApplyBulkCost = async () => {
    if (!bulkCost || selectedProducts.length === 0) return;
    
    const cost = parseFloat(bulkCost);
    if (isNaN(cost)) return;
    
    setIsBulkUpdating(true);
    
    try {
      // Обновляем себестоимость на сервере
      await onBulkCostUpdate(selectedProducts, cost);
      
      // Обновляем локальное состояние
      const updatedCosts = { ...productCosts };
      const updatedSavedCosts = { ...savedCosts };
      
      selectedProducts.forEach(productId => {
        updatedCosts[productId] = cost;
        updatedSavedCosts[productId] = cost;
      });
      
      setProductCosts(updatedCosts);
      setSavedCosts(updatedSavedCosts);
      
      // Очищаем выделение
      setSelectedProducts([]);
      setBulkCost('');
    } finally {
      setIsBulkUpdating(false);
    }
  };
  
  // Обработчик очистки выделения товаров
  const handleClearSelection = () => {
    setSelectedProducts([]);
    setBulkCost('');
  };
  
  // Фильтрация товаров по поиску и категории
  const filteredProducts = products.filter(product => {
    const matchesSearch = searchTerm === '' || 
      product.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      product.offer_id.toLowerCase().includes(searchTerm.toLowerCase());
    
    const matchesCategory = filterCategory === '' || 
      product.category === filterCategory;
    
    return matchesSearch && matchesCategory;
  });
  
  // Получаем доступные категории для фильтра
  const categories = Array.from(new Set(products.map(product => product.category))).filter(Boolean);
  
  // Обработчик изменения страницы
  const handlePageChange = async (pageNumber: number) => {
    // Для серверной пагинации запрашиваем новую страницу с сервера
    if (isServerPagination && onFetchPage) {
      setIsPageLoading(true);
      try {
        await onFetchPage(pageNumber, itemsPerPage);
      } finally {
        setIsPageLoading(false);
      }
    } else {
      // Для клиентской пагинации просто меняем состояние
      setCurrentPage(pageNumber);
    }
  };
  
  // Обработчик изменения количества элементов на странице
  const handleItemsPerPageChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newLimit = parseInt(e.target.value);
    
    // Для серверной пагинации запрашиваем с новым лимитом
    if (isServerPagination && onFetchPage) {
      setIsPageLoading(true);
      try {
        await onFetchPage(1, newLimit);
      } finally {
        setIsPageLoading(false);
      }
    } else {
      // Для клиентской пагинации обновляем состояние
      setItemsPerPage(newLimit);
      setCurrentPage(1);
    }
  };
  
  // Получаем отображаемые товары для клиентской пагинации
  const currentItems = isServerPagination 
    ? filteredProducts 
    : filteredProducts.slice(
        (currentPage - 1) * itemsPerPage,
        currentPage * itemsPerPage
      );
  
  // Расчет общего количества страниц
  const totalPages = Math.ceil(
    (isServerPagination ? totalItems : filteredProducts.length) / itemsPerPage
  );
  
  // Отображаем страницу с учетом загрузки
  const renderPageNumbers = () => {
    const pages = [];
    const maxVisiblePages = 5; // Максимальное количество отображаемых номеров страниц
    
    let startPage = Math.max(1, currentPage - Math.floor(maxVisiblePages / 2));
    let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);
    
    if (endPage - startPage + 1 < maxVisiblePages) {
      startPage = Math.max(1, endPage - maxVisiblePages + 1);
    }
    
    // Кнопка "Предыдущая страница"
    pages.push(
      <button
        key="prev"
        onClick={() => handlePageChange(currentPage - 1)}
        disabled={currentPage === 1 || isPageLoading || isLoading}
        className="pagination-button"
      >
        &laquo;
      </button>
    );
    
    // Номера страниц
    for (let i = startPage; i <= endPage; i++) {
      pages.push(
        <button
          key={i}
          onClick={() => handlePageChange(i)}
          className={`pagination-button ${currentPage === i ? 'active' : ''}`}
          disabled={isPageLoading || isLoading}
        >
          {i}
        </button>
      );
    }
    
    // Кнопка "Следующая страница"
    pages.push(
      <button
        key="next"
        onClick={() => handlePageChange(currentPage + 1)}
        disabled={currentPage === totalPages || isPageLoading || isLoading}
        className="pagination-button"
      >
        &raquo;
      </button>
    );
    
    return pages;
  };
  
  // Информация о количестве товаров и текущем диапазоне
  const renderItemsInfo = () => {
    const from = isServerPagination 
      ? (currentPage - 1) * itemsPerPage + 1 
      : Math.min((currentPage - 1) * itemsPerPage + 1, totalItems);
    
    const to = isServerPagination
      ? Math.min(currentPage * itemsPerPage, totalItems)
      : Math.min(currentPage * itemsPerPage, filteredProducts.length);
    
    return (
      <div className="items-info">
        Показано {from}-{to} из {isServerPagination ? totalItems : filteredProducts.length} товаров
      </div>
    );
  };
  
  return (
    <div className="product-list-container">
      {/* Интерфейс для массового редактирования */}
      {selectedProducts.length > 0 && (
        <div className="bulk-editor">
          <div className="bulk-count">
            Выбрано товаров: {selectedProducts.length}
          </div>
          <div className="bulk-cost-input">
            <label>Установить себестоимость:</label>
            <input
              type="number"
              value={bulkCost}
              onChange={handleBulkCostChange}
              placeholder="Введите себестоимость"
              min="0"
              step="0.01"
              disabled={isBulkUpdating}
            />
          </div>
          <div className="bulk-actions">
            <button
              className="apply-button"
              onClick={handleApplyBulkCost}
              disabled={!bulkCost || isBulkUpdating}
            >
              {isBulkUpdating ? 'Сохранение...' : 'Применить'}
            </button>
            <button
              className="clear-button"
              onClick={handleClearSelection}
              disabled={isBulkUpdating}
            >
              Отменить
            </button>
          </div>
        </div>
      )}
      
      {/* Фильтры для поиска и фильтрации по категории */}
      <div className="filter-container">
        <div className="search-input">
          <input
            type="text"
            placeholder="Поиск по названию или артикулу"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        
        <div className="category-filter">
          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value)}
          >
            <option value="">Все категории</option>
            {categories.map((category, index) => (
              <option key={index} value={category}>
                {category}
              </option>
            ))}
          </select>
        </div>
      </div>
      
      {/* Отображение списка товаров в виде сетки карточек */}
      {isLoading || isPageLoading ? (
        <div className="loading-indicator">Загрузка товаров...</div>
      ) : currentItems.length === 0 ? (
        <div className="no-products">
          Товары не найдены. Попробуйте изменить параметры поиска.
        </div>
      ) : (
        <div className="products-grid">
          {currentItems.map((product) => (
            <div
              key={product.offer_id}
              className={`product-card ${selectedProducts.includes(product.offer_id) ? 'selected' : ''}`}
              onClick={() => handleProductSelect(product.offer_id, !selectedProducts.includes(product.offer_id))}
            >
              <div className="product-image">
                <img
                  src={product.image_url || product.images?.[0] || 'https://via.placeholder.com/150'}
                  alt={product.name}
                />
              </div>
              <div className="product-info">
                <h3 className="product-name">{product.name}</h3>
                <p className="product-id">Артикул: {product.offer_id}</p>
                <p className="product-price">Цена: {product.price} ₽</p>
                
                {product.profit !== undefined && (
                  <p className="product-profit">Прибыль: {product.profit.toFixed(2)} ₽</p>
                )}
                
                {product.margin !== undefined && (
                  <p className="product-margin">Маржа: {product.margin.toFixed(2)}%</p>
                )}
                
                {product.roi !== undefined && (
                  <p className="product-roi">ROI: {product.roi.toFixed(2)}%</p>
                )}
                
                <div className="product-cost-editor" onClick={(e) => e.stopPropagation()}>
                  <label>Себестоимость:</label>
                  <div className="cost-input-container">
                    <input
                      type="number"
                      value={productCosts[product.offer_id] || 0}
                      onChange={(e) => handleCostChange(product.offer_id, e.target.value)}
                      min="0"
                      step="0.01"
                    />
                    {isCostChanged(product.offer_id) && (
                      <button
                        className="save-cost-button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleCostSave(product.offer_id);
                        }}
                        disabled={savingCost[product.offer_id]}
                      >
                        {savingCost[product.offer_id] ? 'Сохранение...' : 'Сохранить'}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      
      {/* Пагинация и выбор количества элементов на странице */}
      <div className="pagination-container">
        {renderItemsInfo()}
        
        <div className="pagination">
          {renderPageNumbers()}
        </div>
        
        <div className="items-per-page">
          <label>Товаров на странице:</label>
          <select
            value={itemsPerPage}
            onChange={handleItemsPerPageChange}
            disabled={isLoading || isPageLoading}
          >
            <option value="10">10</option>
            <option value="20">20</option>
            <option value="50">50</option>
            <option value="100">100</option>
          </select>
        </div>
      </div>
    </div>
  );
};

export default ProductList; 